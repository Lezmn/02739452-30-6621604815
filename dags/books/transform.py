"""Normalize scraped rows into one schema, validate, and de-duplicate across sources."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

NOISE = ["(สินค้าสั่งจอง)", "สินค้าสั่งจอง", "pre-order", "preorder", "หนังสือ", "นิยายสืบสวนสอบสวน", "นิยายสืบสวน", "นิยายแปล", "นิยาย", "ฉบับปรับปรุง",
         "ปกใหม่", "พิมพ์ใหม่", "re-newed", "renewed", "new edition", "ปกอ่อน", "ปกแข็ง"]
PUNCT = re.compile(r"[\s\-–—_:;,.!?\"'“”‘’()\[\]{}<>/\\|#*+=~`@$%^&]+")
EDITION = re.compile(r"(พิมพ์ครั้งที่\s*\d+|พิมพ์\s*\d+|\(.*?พิมพ์.*?\))", re.I)


def clean_title(t: str) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    t = re.sub(r"^หนังสือ\s+", "", t)
    t = re.sub(r"\s+สำนักพิมพ์\s+.+$", "", t)
    return t


def norm_title(t: str) -> str:
    t = EDITION.sub(" ", (t or "").lower())
    for w in NOISE:
        t = t.replace(w, " ")
    return PUNCT.sub("", t)


def clean_isbn(v) -> str | None:
    if not v:
        return None
    d = re.sub(r"[^0-9Xx]", "", str(v))
    return d.upper() if len(d) in (10, 13) else None


def normalize(rows: list[dict], source: str, category: str) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    out = []
    for r in rows:
        title = clean_title(r.get("title") or "")
        price = r.get("price")
        lp = r.get("list_price")
        if lp is not None and price is not None and lp < price:
            price, lp = lp, price
        isbn = clean_isbn(r.get("isbn"))
        tn = norm_title(title)
        out.append({
            "source": source,
            "source_id": str(r.get("source_id") or r.get("url") or title)[:500],
            "title": title[:500],
            "title_norm": tn[:300],
            "author": (r.get("author") or None),
            "publisher": (r.get("publisher") or None),
            "isbn": isbn,
            "price": round(float(price), 2) if price is not None else None,
            "list_price": round(float(lp), 2) if lp else None,
            "discount_pct": round((lp - price) / lp * 100, 1) if lp and price and lp > price else 0.0,
            "url": r.get("url"),
            "image_url": r.get("image_url"),
            "category": category,
            "scraped_at": now,
        })
    return out


def validate(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Row-level quality rules. Returns (valid, invalid-with-reason)."""
    good, bad = [], []
    seen = set()
    for r in rows:
        reason = None
        if not r["title"] or len(r["title"]) < 2:
            reason = "missing_title"
        elif r["price"] is None or not (1 <= r["price"] <= 20000):
            reason = "invalid_price"
        elif (r["source"], r["source_id"]) in seen:
            continue  # same product listed in two categories of one shop -> keep first, not an error
        if reason:
            bad.append({**r, "reason": reason})
        else:
            seen.add((r["source"], r["source_id"]))
            good.append(r)
    return good, bad


def dedup_across_sources(rows: list[dict], threshold: float = 0.88) -> list[dict]:
    """Cluster the same book from different shops: ISBN first, else fuzzy title match.
    Assigns `dedup_key` on each row and returns one unified record per cluster."""
    clusters: list[dict] = []
    by_isbn: dict[str, dict] = {}
    for r in sorted(rows, key=lambda x: (x["isbn"] is None, x["title_norm"])):
        c = by_isbn.get(r["isbn"]) if r["isbn"] else None
        if c is None and r["title_norm"]:
            for cand in clusters:
                if r["source"] in cand["sources"] and cand["title_norm"] != r["title_norm"]:
                    continue
                a, b = cand["title_norm"], r["title_norm"]
                if re.findall(r"\d+", a) != re.findall(r"\d+", b):
                    continue  # different volume / episode number -> different book
                if a == b or (min(len(a), len(b)) >= 6 and (a in b or b in a)) \
                        or SequenceMatcher(None, a, b).ratio() >= threshold:
                    c = cand
                    break
        if c is None:
            key = f"isbn:{r['isbn']}" if r["isbn"] else f"t:{r['title_norm'][:120] or r['source_id']}"
            c = {"dedup_key": key, "title": r["title"], "title_norm": r["title_norm"], "isbn": r["isbn"],
                 "author": r["author"], "sources": set(), "offers": []}
            clusters.append(c)
        if r["isbn"]:
            by_isbn[r["isbn"]] = c
            c["isbn"] = c["isbn"] or r["isbn"]
        c["author"] = c["author"] or r["author"]
        c["sources"].add(r["source"])
        c["offers"].append(r)
        r["dedup_key"] = c["dedup_key"]

    unified = []
    for c in clusters:
        cheapest = min(c["offers"], key=lambda o: o["price"])
        prices = [o["price"] for o in c["offers"]]
        unified.append({
            "dedup_key": c["dedup_key"][:300], "title": c["title"], "author": c["author"], "isbn": c["isbn"],
            "n_sources": len(c["sources"]), "sources": sorted(c["sources"]),
            "min_price": min(prices), "max_price": max(prices),
            "cheapest_source": cheapest["source"], "cheapest_url": cheapest["url"],
            "image_url": next((o["image_url"] for o in c["offers"] if o["image_url"]), None),
        })
    return unified
