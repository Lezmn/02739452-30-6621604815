"""PostgreSQL schema + UPSERT helpers."""
from __future__ import annotations

import json

import psycopg2
from psycopg2.extras import execute_values

from books.config import DB_URL

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    source        TEXT        NOT NULL,
    source_id     TEXT        NOT NULL,
    title         TEXT        NOT NULL,
    title_norm    TEXT,
    author        TEXT,
    publisher     TEXT,
    isbn          TEXT,
    price         NUMERIC(10,2) NOT NULL,
    list_price    NUMERIC(10,2),
    discount_pct  NUMERIC(5,1) DEFAULT 0,
    url           TEXT,
    image_url     TEXT,
    category      TEXT,
    dedup_key     TEXT,
    scraped_at    TIMESTAMPTZ NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_books_dedup ON books(dedup_key);

CREATE TABLE IF NOT EXISTS books_unified (
    dedup_key       TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    author          TEXT,
    isbn            TEXT,
    n_sources       INT,
    sources         TEXT[],
    min_price       NUMERIC(10,2),
    max_price       NUMERIC(10,2),
    cheapest_source TEXT,
    cheapest_url    TEXT,
    image_url       TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS books_quarantine (
    id         BIGSERIAL PRIMARY KEY,
    run_id     TEXT,
    source     TEXT,
    reason     TEXT,
    payload    JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id         TEXT PRIMARY KEY,
    started_at     TIMESTAMPTZ,
    finished_at    TIMESTAMPTZ,
    status         TEXT,
    branch         TEXT,
    source_status  JSONB,
    rows_valid     INT,
    rows_invalid   INT,
    rows_unified   INT,
    message        TEXT
);
"""

BOOK_COLS = ["source", "source_id", "title", "title_norm", "author", "publisher", "isbn", "price",
             "list_price", "discount_pct", "url", "image_url", "category", "dedup_key", "scraped_at"]


def connect():
    return psycopg2.connect(DB_URL)


def create_tables():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(SCHEMA)


def upsert_books(rows: list[dict]) -> int:
    if not rows:
        return 0
    sql = f"""
        INSERT INTO books ({", ".join(BOOK_COLS)}) VALUES %s
        ON CONFLICT (source, source_id) DO UPDATE SET
          {", ".join(f"{c} = EXCLUDED.{c}" for c in BOOK_COLS if c not in ("source", "source_id"))},
          updated_at = now()
    """
    rows = list({(r["source"], r["source_id"]): r for r in rows}.values())  # no dup keys in one batch
    values = [tuple(r.get(c) for c in BOOK_COLS) for r in rows]
    with connect() as conn, conn.cursor() as cur:
        execute_values(cur, sql, values, page_size=500)
    return len(values)


UNI_COLS = ["dedup_key", "title", "author", "isbn", "n_sources", "sources", "min_price", "max_price",
            "cheapest_source", "cheapest_url", "image_url"]


def upsert_unified(rows: list[dict]) -> int:
    if not rows:
        return 0
    sql = f"""
        INSERT INTO books_unified ({", ".join(UNI_COLS)}) VALUES %s
        ON CONFLICT (dedup_key) DO UPDATE SET
          {", ".join(f"{c} = EXCLUDED.{c}" for c in UNI_COLS if c != "dedup_key")},
          updated_at = now()
    """
    rows = list({r["dedup_key"]: r for r in rows}.values())
    values = [tuple(r.get(c) for c in UNI_COLS) for r in rows]
    with connect() as conn, conn.cursor() as cur:
        execute_values(cur, sql, values, page_size=500)
    return len(values)


def insert_quarantine(run_id: str, rows: list[dict]):
    if not rows:
        return
    with connect() as conn, conn.cursor() as cur:
        execute_values(cur, "INSERT INTO books_quarantine (run_id, source, reason, payload) VALUES %s",
                       [(run_id, r.get("source"), r.get("reason"), json.dumps(r, ensure_ascii=False, default=str))
                        for r in rows])


def upsert_run(run: dict):
    cols = list(run.keys())
    vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in run.values()]
    sql = f"""
        INSERT INTO pipeline_runs ({", ".join(cols)}) VALUES ({", ".join(["%s"] * len(cols))})
        ON CONFLICT (run_id) DO UPDATE SET {", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "run_id")}
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, vals)
