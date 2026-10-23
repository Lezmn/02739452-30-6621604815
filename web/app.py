"""Dashboard: reads PostgreSQL directly (psycopg2)."""
import os

import psycopg2
import psycopg2.extras
from flask import Flask, render_template, request

DB_URL = os.getenv("BOOKS_DB_URL", "postgresql://airflow:airflow@localhost:5432/books")
LABELS = {"seed": "SE-ED", "b2s": "B2S", "amarin": "Amarinbooks", "naiin": "นายอินทร์"}

app = Flask(__name__)


def q(sql, params=None):
    with psycopg2.connect(DB_URL) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


def safe(fn, default):
    try:
        return fn()
    except psycopg2.Error as e:  # tables not created yet etc.
        app.logger.warning("db error: %s", e)
        return default


@app.template_filter("baht")
def baht(v):
    return "-" if v is None else f"฿{float(v):,.0f}"


@app.context_processor
def inject():
    return {"LABELS": LABELS}


@app.route("/")
def index():
    src = request.args.getlist("source")
    term = request.args.get("q", "").strip()
    pmin = request.args.get("min", type=float)
    pmax = request.args.get("max", type=float)
    discount = request.args.get("discount") == "1"
    sort = request.args.get("sort", "price_asc")

    where, params = ["TRUE"], []
    if src:
        where.append("source = ANY(%s)"); params.append(src)
    if term:
        where.append("(title ILIKE %s OR author ILIKE %s)"); params += [f"%{term}%"] * 2
    if pmin is not None:
        where.append("price >= %s"); params.append(pmin)
    if pmax is not None:
        where.append("price <= %s"); params.append(pmax)
    if discount:
        where.append("discount_pct > 0")
    w = " AND ".join(where)
    order = {"price_asc": "price ASC", "price_desc": "price DESC", "discount": "discount_pct DESC",
             "title": "title ASC", "new": "updated_at DESC"}.get(sort, "price ASC")

    kpi = safe(lambda: q(f"""
        SELECT COUNT(*) AS n, COUNT(DISTINCT dedup_key) AS uniq, ROUND(AVG(price),0) AS avg_price,
               MIN(price) AS min_price, MAX(price) AS max_price,
               ROUND(AVG(NULLIF(discount_pct,0)),1) AS avg_disc, MAX(updated_at) AS last_update
        FROM books WHERE {w}""", params)[0], {})
    by_source = safe(lambda: q(f"""
        SELECT source, COUNT(*) AS n, ROUND(AVG(price),0) AS avg_price, MIN(price) AS min_price
        FROM books WHERE {w} GROUP BY source ORDER BY source""", params), [])
    hist = safe(lambda: q(f"""
        SELECT LEAST(FLOOR(price/100)*100, 1000)::int AS bucket, COUNT(*) AS n
        FROM books WHERE {w} GROUP BY 1 ORDER BY 1""", params), [])
    rows = safe(lambda: q(f"""
        SELECT b.*, u.n_sources FROM books b LEFT JOIN books_unified u USING (dedup_key)
        WHERE {w} ORDER BY {order} LIMIT 500""", params), [])
    multi = safe(lambda: q("SELECT COUNT(*) AS n FROM books_unified WHERE n_sources > 1")[0]["n"], 0)
    all_sources = safe(lambda: [r["source"] for r in q("SELECT DISTINCT source FROM books ORDER BY 1")], [])

    return render_template("index.html", kpi=kpi, by_source=by_source, hist=hist, rows=rows,
                           multi=multi, all_sources=all_sources,
                           f={"source": src, "q": term, "min": pmin, "max": pmax,
                              "discount": discount, "sort": sort})


@app.route("/compare")
def compare():
    rows = safe(lambda: q("""
        SELECT u.*, (u.max_price - u.min_price) AS diff,
               json_agg(json_build_object('source', b.source, 'price', b.price, 'url', b.url)
                        ORDER BY b.price) AS offers
        FROM books_unified u JOIN books b USING (dedup_key)
        WHERE u.n_sources > 1
        GROUP BY u.dedup_key ORDER BY diff DESC, u.title LIMIT 300"""), [])
    return render_template("compare.html", rows=rows)


@app.route("/status")
def status():
    runs = safe(lambda: q("SELECT * FROM pipeline_runs ORDER BY started_at DESC NULLS LAST LIMIT 30"), [])
    quarantine = safe(lambda: q("""
        SELECT reason, source, COUNT(*) AS n, MAX(created_at) AS last
        FROM books_quarantine GROUP BY reason, source ORDER BY last DESC LIMIT 20"""), [])
    return render_template("status.html", runs=runs, quarantine=quarantine)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
