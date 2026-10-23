"""Source configuration. Override any URL with env var SOURCE_<NAME>_URLS (comma separated)."""
import os

# {page} is replaced with 1..max_pages
SOURCES = {
    "seed": {
        "label": "SE-ED",
        "urls": [
            # Page is rendered by JavaScript; call the public search API it uses (no token needed).
            # category book-dhijad-t1wg1l = นิยายสืบสวน ซ่อนเงื่อน สยองขวัญ ({skip} = (page-1)*48)
            "https://mp-api.se-ed.com/web-bff/search-product?filter.categoryId=book-dhijad-t1wg1l&option.limit=48&option.skip={skip}&sorter=PRODUCT_SORTER_NEWEST",
        ],
        "parser": "seed_api",
        "max_pages": 6,
    },
    "bookcaze": {
        "label": "Bookcaze",
        "urls": [
            # OpenCart, server-rendered HTML (verified). Several mystery keywords, 100 per page.
            "https://www.bookcaze.com/index.php?route=product/search&search=%E0%B8%AA%E0%B8%B7%E0%B8%9A%E0%B8%AA%E0%B8%A7%E0%B8%99&limit=100&page={page}",
            "https://www.bookcaze.com/index.php?route=product/search&search=%E0%B8%86%E0%B8%B2%E0%B8%95%E0%B8%81%E0%B8%A3%E0%B8%A3%E0%B8%A1&limit=100&page={page}",
            "https://www.bookcaze.com/index.php?route=product/search&search=%E0%B8%9B%E0%B8%A3%E0%B8%B4%E0%B8%A8%E0%B8%99%E0%B8%B2&limit=100&page={page}",
            "https://www.bookcaze.com/index.php?route=product/search&search=agatha&limit=100&page={page}",
            "https://www.bookcaze.com/index.php?route=product/search&search=%E0%B9%80%E0%B8%8A%E0%B8%AD%E0%B8%A3%E0%B9%8C%E0%B8%A5%E0%B9%87%E0%B8%AD%E0%B8%81&limit=100&page={page}",
        ],
        "parser": "opencart",
        "max_pages": 2,
    },
    "b2s": {
        "label": "B2S",
        "urls": [
            # Product list is rendered by JavaScript; we call the same public catalog API the page uses
            # (guest token in B2S_API_TOKEN). Category 666d...122f = นิยายสืบสวนสอบสวน
            "https://b2sp-gw.b2s.co.th/b2s/product/api/v1/CatalogProducts?account_channel=standard&user_category_type=Standard&company_id=&default_sort=promotion&page={page}&page_size=30&categories=666d6731e02e2998486e122f&sort=promotion&is_facet_only=false",
        ],
        "parser": "b2s_api",
        "max_pages": 16,
    },
    "amarin": {
        "label": "Amarinbooks",
        "urls": [
            # WooCommerce, server-rendered HTML (verified)
            "https://amarinbooks.com/product-category/%e0%b8%99%e0%b8%b4%e0%b8%a2%e0%b8%b2%e0%b8%a2%e0%b8%aa%e0%b8%b7%e0%b8%9a%e0%b8%aa%e0%b8%a7%e0%b8%99/page/{page}/",
            "https://amarinbooks.com/product-category/%e0%b8%99%e0%b8%b4%e0%b8%a2%e0%b8%b2%e0%b8%a2%e0%b8%aa%e0%b8%b4%e0%b8%9a%e0%b8%aa%e0%b8%a7%e0%b8%99/page/{page}/",
        ],
        "parser": "woocommerce",
        "max_pages": 5,
    },
    # Disabled by default: naiin blocks bots / renders with JS. Enable with ENABLED_SOURCES.
    "naiin": {
        "label": "นายอินทร์",
        "urls": [
            "https://www.naiin.com/category?category_1_code=2&product_type_id=1&categoryLv2Code=8&page={page}",
        ],
        "parser": "auto",
        "max_pages": 5,
    },
}

ENABLED_SOURCES = [s.strip() for s in os.getenv("ENABLED_SOURCES", "seed,b2s,amarin,bookcaze").split(",") if s.strip()]

for _name, _cfg in SOURCES.items():
    _env = os.getenv(f"SOURCE_{_name.upper()}_URLS")
    if _env:
        _cfg["urls"] = [u.strip() for u in _env.split(",") if u.strip()]

CATEGORY = "นิยายสืบสวนสอบสวน/ลึกลับ (Mystery)"
DATA_DIR = os.getenv("BOOKS_DATA_DIR", "/opt/airflow/data")
DB_URL = os.getenv("BOOKS_DB_URL", "postgresql://airflow:airflow@postgres:5432/books")

# Quality gate
MIN_VALID_RATIO = float(os.getenv("MIN_VALID_RATIO", "0.8"))
MIN_TOTAL_ROWS = int(os.getenv("MIN_TOTAL_ROWS", "1"))
