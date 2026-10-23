"""Quick test of the scrapers WITHOUT Airflow/Docker.

    pip install requests beautifulsoup4 lxml
    python scripts/probe.py            # all enabled sources, 1 page each
    python scripts/probe.py b2s 3      # one source, 3 pages
"""
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "dags"))

# load ../.env (docker compose reads it automatically; plain python does not)
_env_path = os.path.join(ROOT, ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8-sig") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                _v = _v.strip().strip('"').strip("'")
                if _v.lower().startswith("bearer "):
                    _v = _v[7:]
                os.environ.setdefault(_k.strip(), _v)

from books.config import ENABLED_SOURCES, SOURCES  # noqa: E402
import json  # noqa: E402

from books.scraper import PARSERS, extract_products, fetch, robots_allowed, scrape_listing  # noqa: E402

names = [sys.argv[1]] if len(sys.argv) > 1 else ENABLED_SOURCES
pages = int(sys.argv[2]) if len(sys.argv) > 2 else 1

for name in names:
    cfg = SOURCES[name]
    print(f"\n=== {cfg['label']} ({name}) ===")
    for tpl in cfg["urls"]:
        url = tpl.format(page=1, skip=0)
        print("URL:", url[:120])
        print("robots.txt allowed:", robots_allowed(url))
        try:
            if cfg["parser"].endswith("_api"):
                rows = scrape_listing(tpl, max_pages=pages, parser=cfg["parser"])
                print(f"{pages} page(s) -> {len(rows)} items via {cfg['parser']}")
                for it in rows[:5]:
                    print(f"   {it['price']:>8} | {it['list_price']} | {it['title'][:60]} | {it['url']}")
                continue
            html = fetch(url)
            print("HTML bytes:", len(html), "| __NEXT_DATA__:", "__NEXT_DATA__" in html,
                  "| __NUXT_DATA__:", "__NUXT_DATA__" in html, "| window.__NUXT__:", "window.__NUXT__" in html,
                  "| ld+json:", "application/ld+json" in html, "| '฿' or 'บาท':", ("฿" in html or "บาท" in html))
            items, method = (PARSERS[cfg["parser"]](html, url), cfg["parser"]) if cfg["parser"] in PARSERS \
                else extract_products(html, url)
            print(f"page1 -> {len(items)} items via {method}")
            for it in items[:5]:
                print(f"   {it['price']:>8} | {it['list_price']} | {it['title'][:60]} | {it['isbn']}")
            if pages > 1:
                rows = scrape_listing(tpl, max_pages=pages, parser=cfg["parser"])
                print(f"{pages} pages -> {len(rows)} items")
        except Exception as e:  # noqa: BLE001
            print("ERROR:", type(e).__name__, e)
