"""Generic book-listing scraper (requests + BeautifulSoup, no Selenium).

Extraction order for each page:
  1. JSON-LD (<script type="application/ld+json">) Product / ItemList
  2. Next.js  <script id="__NEXT_DATA__">
  3. Nuxt 3   <script id="__NUXT_DATA__">  (devalue format)
  4. HTML heuristic: product cards that contain a link + a Thai-baht price
Only book data is collected (no personal data -> PDPA safe).
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; KU-02739452-student-project/1.0; educational use)"
TIMEOUT = 20

TITLE_KEYS = ("name", "title", "productName", "product_name", "bookName", "book_name")
PRICE_KEYS = ("salePrice", "sale_price", "finalPrice", "final_price", "specialPrice",
              "special_price", "sellingPrice", "priceAfterDiscount", "netPrice", "price")
LIST_PRICE_KEYS = ("fullPrice", "full_price", "listPrice", "list_price", "regularPrice",
                   "regular_price", "originalPrice", "original_price", "coverPrice", "basePrice")
ISBN_KEYS = ("isbn", "isbn13", "ISBN", "barcode", "gtin13", "ean")
AUTHOR_KEYS = ("author", "authorName", "author_name", "authors", "writer")
PUBLISHER_KEYS = ("publisher", "publisherName", "publisher_name", "brand", "brandName")
URL_KEYS = ("url", "link", "productUrl", "product_url", "href", "slug", "urlKey", "url_key")
IMAGE_KEYS = ("image", "imageUrl", "image_url", "thumbnail", "cover", "img")
ID_KEYS = ("sku", "id", "productId", "product_id", "code")

PRICE_RE = re.compile(r"(?:฿\s*|THB\s*)?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s*(?:บาท|฿|THB)?")
BAHT_RE = re.compile(r"(?:฿\s*(\d[\d,]*(?:\.\d+)?))|(?:(\d[\d,]*(?:\.\d+)?)\s*(?:บาท|฿|THB))")


# --------------------------------------------------------------------------- HTTP
_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}


def robots_allowed(url: str) -> bool:
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    rp = _robots_cache.get(base)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            rp.parse([])  # cannot read robots -> treat as allowed (standard behaviour)
        _robots_cache[base] = rp
    return rp.can_fetch(USER_AGENT, url)


def fetch(url: str) -> str:
    if not robots_allowed(url):
        raise PermissionError(f"robots.txt disallows {url}")
    r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "th,en;q=0.8"},
                     timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.encoding or "utf-8"
    return r.text


# --------------------------------------------------------------------------- helpers
def to_price(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, dict):
        for k in ("price", "value", "amount", "lowPrice"):
            if k in v:
                return to_price(v[k])
        return None
    else:
        m = PRICE_RE.search(str(v).replace("\xa0", " "))
        if not m:
            return None
        f = float(m.group(1).replace(",", ""))
    return f if 1 <= f <= 100000 else None


def _first(d: dict, keys):
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return None


def _text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v.strip() or None
    if isinstance(v, dict):
        return _text(_first(v, ("name", "title", "value", "url")))
    if isinstance(v, list):
        parts = [t for t in (_text(x) for x in v) if t]
        return ", ".join(parts) or None
    return str(v)


def _record_from_dict(d: dict, base_url: str) -> dict | None:
    title = _text(_first(d, TITLE_KEYS))
    if not title or len(title) < 2:
        return None
    price_raw = _first(d, PRICE_KEYS)
    if price_raw is None and isinstance(d.get("offers"), (dict, list)):
        offers = d["offers"][0] if isinstance(d["offers"], list) and d["offers"] else d["offers"]
        price_raw = offers.get("price") if isinstance(offers, dict) else None
    price = to_price(price_raw)
    if price is None:
        return None
    url = _text(_first(d, URL_KEYS))
    if url and not url.startswith("http"):
        url = urljoin(base_url, url)
    img = _text(_first(d, IMAGE_KEYS))
    return {
        "source_id": str(_first(d, ID_KEYS) or url or title),
        "title": title,
        "author": _text(_first(d, AUTHOR_KEYS)),
        "publisher": _text(_first(d, PUBLISHER_KEYS)),
        "isbn": _text(_first(d, ISBN_KEYS)),
        "price": price,
        "list_price": to_price(_first(d, LIST_PRICE_KEYS)),
        "url": url,
        "image_url": img if img and img.startswith("http") else None,
    }


def walk_json(obj, base_url: str, out: list, depth: int = 0):
    """Recursively find dicts that look like products (title + price)."""
    if depth > 40:
        return
    if isinstance(obj, dict):
        rec = _record_from_dict(obj, base_url)
        if rec:
            out.append(rec)
            return
        for v in obj.values():
            walk_json(v, base_url, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            walk_json(v, base_url, out, depth + 1)


def devalue_hydrate(arr: list):
    """Decode Nuxt 3 __NUXT_DATA__ (devalue) into plain Python objects."""
    memo: dict[int, object] = {}

    def h(i):
        if not isinstance(i, int) or i < 0 or i >= len(arr):
            return None
        if i in memo:
            return memo[i]
        v = arr[i]
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in ("Reactive", "ShallowReactive", "Ref", "ShallowRef", "EmptyRef"):
                memo[i] = None
                res = h(v[1]) if len(v) > 1 else None
            elif v and isinstance(v[0], str) and v[0] in ("Date", "BigInt", "RegExp"):
                res = v[1] if len(v) > 1 else None
            elif v and isinstance(v[0], str) and v[0] in ("Set", "Map", "null"):
                res = [h(x) for x in v[1:]]
            else:
                res = []
                memo[i] = res
                res.extend(h(x) for x in v)
        elif isinstance(v, dict):
            res = {}
            memo[i] = res
            for k, x in v.items():
                res[k] = h(x)
        else:
            res = v
        memo[i] = res
        return res

    return h(0)


def _html_cards(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Fallback: find small DOM blocks with one product link and a baht price."""
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        title = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
        if len(title) < 3 or len(title) > 200:
            continue
        card = a
        for _ in range(5):  # climb up to the product card
            card = card.parent
            if card is None:
                break
            txt = card.get_text(" ", strip=True)
            if len(txt) > 600:
                card = None
                break
            prices = [to_price(m.group(1) or m.group(2)) for m in BAHT_RE.finditer(txt)]
            prices = [p for p in prices if p]
            if prices:
                href = urljoin(base_url, a["href"])
                if href in seen:
                    break
                seen.add(href)
                img = card.find("img")
                out.append({
                    "source_id": href, "title": title, "author": None, "publisher": None,
                    "isbn": None, "price": min(prices),
                    "list_price": max(prices) if len(prices) > 1 else None,
                    "url": href,
                    "image_url": (img.get("src") or img.get("data-src")) if img else None,
                })
                break
    return out


def extract_products(html: str, base_url: str) -> tuple[list[dict], str]:
    soup = BeautifulSoup(html, "lxml")
    found: list[dict] = []

    for s in soup.find_all("script", type="application/ld+json"):
        try:
            walk_json(json.loads(s.string or ""), base_url, found)
        except (json.JSONDecodeError, TypeError):
            pass
    if found:
        return found, "json-ld"

    s = soup.find("script", id="__NEXT_DATA__")
    if s and s.string:
        try:
            walk_json(json.loads(s.string), base_url, found)
        except json.JSONDecodeError:
            pass
        if found:
            return found, "next-data"

    s = soup.find("script", id="__NUXT_DATA__")
    if s and s.string:
        try:
            walk_json(devalue_hydrate(json.loads(s.string)), base_url, found)
        except (json.JSONDecodeError, RecursionError):
            pass
        if found:
            return found, "nuxt-data"

    return _html_cards(soup, base_url), "html"


def parse_woocommerce(html: str, base_url: str) -> list[dict]:
    """WooCommerce product grid (li.product). Sale price = <ins>, list price = <del>."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for li in soup.select("li.product, div.product.type-product"):
        a = li.select_one("a.woocommerce-LoopProduct-link, a[href*='/product/']") or li.find("a", href=True)
        t = li.select_one(".woocommerce-loop-product__title, h2, h3")
        if not a or not t:
            continue
        price_el = li.select_one(".price")
        if not price_el:
            continue
        ins, dele = price_el.select_one("ins"), price_el.select_one("del")
        price = to_price((ins or price_el).get_text(" ", strip=True))
        list_price = to_price(dele.get_text(" ", strip=True)) if dele else None
        if price is None:
            continue
        sku_el = li.select_one("[data-product_sku]")
        img = li.find("img")
        href = urljoin(base_url, a["href"])
        out.append({
            "source_id": (sku_el.get("data-product_id") if sku_el else None) or href,
            "title": t.get_text(" ", strip=True),
            "author": None, "publisher": None,
            "isbn": (sku_el.get("data-product_sku") if sku_el else None) or None,
            "price": price, "list_price": list_price, "url": href,
            "image_url": (img.get("data-src") or img.get("src")) if img else None,
        })
    return out


def scrape_listing(url_template: str, max_pages: int = 5, delay: float = 1.5,
                   parser: str = "auto") -> list[dict]:
    """Scrape pages 1..max_pages of a category listing. `{page}` in the template is replaced."""
    rows: list[dict] = []
    seen_ids: set[str] = set()
    for page in range(1, max_pages + 1):
        url = url_template.format(page=page)
        try:
            html = fetch(url)
        except requests.HTTPError as e:
            if page > 1 and e.response is not None and e.response.status_code == 404:
                break  # past the last page
            raise
        if parser == "woocommerce":
            items, method = parse_woocommerce(html, url), "woocommerce"
            if not items:
                items, method = extract_products(html, url)
        else:
            items, method = extract_products(html, url)
        new = [r for r in items if r["source_id"] not in seen_ids]
        log.info("%s -> %d items (%d new) via %s", url, len(items), len(new), method)
        if not new:
            break
        for r in new:
            seen_ids.add(r["source_id"])
        rows.extend(new)
        if "{page}" not in url_template:
            break
        time.sleep(delay)  # be polite
    return rows
