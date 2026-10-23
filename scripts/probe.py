"""Quick test of the scrapers WITHOUT Airflow/Docker.

    pip install requests beautifulsoup4 lxml
    python scripts/probe.py            # all enabled sources, 1 page each
    python scripts/probe.py b2s 3      # one source, 3 pages
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dags"))

from books.config import ENABLED_SOURCES, SOURCES  # noqa: E402
from books.scraper import extract_products, fetch, parse_woocommerce, robots_allowed, scrape_listing  # noqa: E402

names = [sys.argv[1]] if len(sys.argv) > 1 else ENABLED_SOURCES
pages = int(sys.argv[2]) if len(sys.argv) > 2 else 1

for name in names:
    cfg = SOURCES[name]
    print(f"\n=== {cfg['label']} ({name}) ===")
    for tpl in cfg["urls"]:
        url = tpl.format(page=1)
        print("URL:", url[:120])
        print("robots.txt allowed:", robots_allowed(url))
        try:
            html = fetch(url)
            print("HTML bytes:", len(html), "| __NEXT_DATA__:", "__NEXT_DATA__" in html,
                  "| __NUXT_DATA__:", "__NUXT_DATA__" in html, "| window.__NUXT__:", "window.__NUXT__" in html,
                  "| ld+json:", "application/ld+json" in html, "| '฿' or 'บาท':", ("฿" in html or "บาท" in html))
            items, method = (parse_woocommerce(html, url), "woocommerce") if cfg["parser"] == "woocommerce" \
                else extract_products(html, url)
            print(f"page1 -> {len(items)} items via {method}")
            for it in items[:5]:
                print(f"   {it['price']:>8} | {it['list_price']} | {it['title'][:60]} | {it['isbn']}")
            if pages > 1:
                rows = scrape_listing(tpl, max_pages=pages, parser=cfg["parser"])
                print(f"{pages} pages -> {len(rows)} items")
        except Exception as e:  # noqa: BLE001
            print("ERROR:", type(e).__name__, e)
