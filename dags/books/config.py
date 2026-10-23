"""Source configuration. Override any URL with env var SOURCE_<NAME>_URLS (comma separated)."""
import os

# {page} is replaced with 1..max_pages
SOURCES = {
    "seed": {
        "label": "SE-ED",
        "urls": [
            "https://www.se-ed.com/%E0%B8%AA%E0%B8%B7%E0%B8%9A%E0%B8%AA%E0%B8%A7%E0%B8%99%E0%B8%AA%E0%B8%AD%E0%B8%9A%E0%B8%AA%E0%B8%A7%E0%B8%99%2F%E0%B8%AA%E0%B8%A2%E0%B8%AD%E0%B8%87%E0%B8%82%E0%B8%A7%E0%B8%B1%E0%B8%8D-cat.book-3hmmpo-lz4zok?page={page}",
        ],
        "parser": "auto",
        "max_pages": 5,
    },
    "b2s": {
        "label": "B2S",
        "urls": [
            "https://www.b2s.co.th/category/%E0%B8%AB%E0%B8%99%E0%B8%B1%E0%B8%87%E0%B8%AA%E0%B8%B7%E0%B8%AD/%E0%B8%AB%E0%B8%99%E0%B8%B1%E0%B8%87%E0%B8%AA%E0%B8%B7%E0%B8%AD%E0%B8%99%E0%B8%B4%E0%B8%A2%E0%B8%B2%E0%B8%A2-%E0%B8%A7%E0%B8%A3%E0%B8%A3%E0%B8%93%E0%B8%81%E0%B8%A3%E0%B8%A3%E0%B8%A1/%E0%B8%99%E0%B8%B4%E0%B8%A2%E0%B8%B2%E0%B8%A2%E0%B8%AA%E0%B8%B7%E0%B8%9A%E0%B8%AA%E0%B8%A7%E0%B8%99%E0%B8%AA%E0%B8%AD%E0%B8%9A%E0%B8%AA%E0%B8%A7%E0%B8%99?page={page}",
        ],
        "parser": "auto",
        "max_pages": 5,
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

ENABLED_SOURCES = [s.strip() for s in os.getenv("ENABLED_SOURCES", "seed,b2s,amarin").split(",") if s.strip()]

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
