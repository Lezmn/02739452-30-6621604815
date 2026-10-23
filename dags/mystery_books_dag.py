"""
Mystery-novel prices from Thai online bookstores (SE-ED, B2S, Amarinbooks)
extract (parallel TaskGroup) -> transform -> merge/dedup -> quality branch -> UPSERT PostgreSQL
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone

from airflow.decorators import dag, task, task_group
from airflow.utils.state import TaskInstanceState
from airflow.utils.trigger_rule import TriggerRule

from books import db
from books.config import (CATEGORY, DATA_DIR, ENABLED_SOURCES, MIN_TOTAL_ROWS,
                          MIN_VALID_RATIO, SOURCES)
from books.scraper import scrape_listing
from books.transform import dedup_across_sources, normalize, validate


def run_dir(run_id: str) -> str:
    d = os.path.join(DATA_DIR, re.sub(r"[^A-Za-z0-9_.-]", "_", run_id))
    os.makedirs(d, exist_ok=True)
    return d


def dump(path: str, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, default=str)


def load(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@dag(
    dag_id="mystery_books_pipeline",
    description="รวมราคานิยายสืบสวนสอบสวนจากร้านหนังสือออนไลน์ไทย 3 แหล่ง",
    schedule="0 */6 * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"owner": "student", "retries": 1, "retry_delay": timedelta(seconds=20)},
    tags=["02739452", "books", "scraping"],
)
def mystery_books_pipeline():

    @task
    def create_tables():
        db.create_tables()

    @task
    def start_run(**ctx):
        db.upsert_run({"run_id": ctx["run_id"], "started_at": datetime.now(timezone.utc),
                       "status": "running"})

    def source_group(name: str):
        cfg = SOURCES[name]

        @task_group(group_id=name, tooltip=cfg["label"])
        def grp():
            @task(task_id="extract")
            def extract(**ctx) -> str:
                rows = []
                for url in cfg["urls"]:
                    rows += scrape_listing(url, max_pages=cfg["max_pages"], parser=cfg["parser"])
                if not rows:
                    raise ValueError(f"{cfg['label']}: scraped 0 rows (site changed or blocked?)")
                path = os.path.join(run_dir(ctx["run_id"]), f"raw_{name}.json")
                dump(path, rows)
                print(f"{name}: {len(rows)} raw rows -> {path}")
                return path

            @task(task_id="transform")
            def transform(raw_path: str, **ctx) -> int:
                rows = normalize(load(raw_path), name, CATEGORY)
                dump(os.path.join(run_dir(ctx["run_id"]), f"clean_{name}.json"), rows)
                return len(rows)

            transform(extract())

        return grp()

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def merge(**ctx) -> dict:
        """Runs even if some sources failed; fails only when every source failed."""
        d = run_dir(ctx["run_id"])
        rows, ok = [], []
        for name in ENABLED_SOURCES:
            p = os.path.join(d, f"clean_{name}.json")
            if os.path.exists(p):
                rows += load(p)
                ok.append(name)
        if not ok:
            raise RuntimeError("all sources failed")
        valid, invalid = validate(rows)
        unified = dedup_across_sources(valid)
        dump(os.path.join(d, "valid.json"), valid)
        dump(os.path.join(d, "invalid.json"), invalid)
        dump(os.path.join(d, "unified.json"), unified)
        stats = {"sources_ok": ok, "rows_total": len(rows), "rows_valid": len(valid),
                 "rows_invalid": len(invalid), "rows_unified": len(unified),
                 "valid_ratio": round(len(valid) / (len(valid) + len(invalid)), 3) if valid or invalid else 0}
        print(stats)
        return stats

    @task.branch
    def quality_check(stats: dict) -> str:
        passed = stats["rows_valid"] >= MIN_TOTAL_ROWS and stats["valid_ratio"] >= MIN_VALID_RATIO
        print("quality", "PASSED" if passed else "FAILED", stats)
        return "load_postgres" if passed else "quarantine_batch"

    @task
    def load_postgres(**ctx):
        d = run_dir(ctx["run_id"])
        n = db.upsert_books(load(os.path.join(d, "valid.json")))
        u = db.upsert_unified(load(os.path.join(d, "unified.json")))
        db.insert_quarantine(ctx["run_id"], load(os.path.join(d, "invalid.json")))
        print(f"upserted books={n} unified={u}")

    @task
    def quarantine_batch(**ctx):
        d = run_dir(ctx["run_id"])
        rows = [{**r, "reason": "batch_failed_quality"} for r in load(os.path.join(d, "valid.json"))]
        db.insert_quarantine(ctx["run_id"], rows + load(os.path.join(d, "invalid.json")))
        print(f"quarantined {len(rows)} rows; production tables untouched")

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def finalize_run(**ctx):
        dr = ctx["dag_run"]
        st = {ti.task_id: ti.state for ti in dr.get_task_instances()}
        source_status = {}
        for name in ENABLED_SOURCES:
            states = [st.get(f"sources.{name}.extract"), st.get(f"sources.{name}.transform")]
            source_status[name] = "success" if all(s == TaskInstanceState.SUCCESS for s in states) else "failed"
        stats = ctx["ti"].xcom_pull(task_ids="merge") or {}
        if st.get("load_postgres") == TaskInstanceState.SUCCESS:
            status = "success" if all(v == "success" for v in source_status.values()) else "partial"
            branch = "load_postgres"
        elif st.get("quarantine_batch") == TaskInstanceState.SUCCESS:
            status, branch = "quality_failed", "quarantine_batch"
        else:
            status, branch = "failed", None
        db.upsert_run({
            "run_id": ctx["run_id"], "finished_at": datetime.now(timezone.utc), "status": status,
            "branch": branch, "source_status": source_status,
            "rows_valid": stats.get("rows_valid"), "rows_invalid": stats.get("rows_invalid"),
            "rows_unified": stats.get("rows_unified"),
            "message": json.dumps(stats, ensure_ascii=False),
        })

    @task_group(group_id="sources", tooltip="ดึงข้อมูลทุกแหล่งขนานกัน")
    def sources():
        for name in ENABLED_SOURCES:
            source_group(name)

    t_create, t_start = create_tables(), start_run()
    g = sources()
    stats = merge()
    branch = quality_check(stats)
    t_load, t_quar = load_postgres(), quarantine_batch()
    t_final = finalize_run()

    t_create >> t_start >> g >> stats
    branch >> [t_load, t_quar]
    [t_load, t_quar] >> t_final


mystery_books_pipeline()
