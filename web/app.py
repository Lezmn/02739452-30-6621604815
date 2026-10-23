"""Dashboard: reads PostgreSQL directly (psycopg2)."""
import os

import psycopg2
import psycopg2.extras
from flask import Flask, render_template, request

DB_URL = os.getenv("BOOKS_DB_URL", "postgresql://airflow:airflow@localhost:5432/books")
LABELS = {"seed": "SE-ED", "bookcaze": "Bookcaze", "b2s": "B2S", "amarin": "Amarinbooks", "naiin": "นายอินทร์"}

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
    srcs = safe(lambda: [r["source"] for r in q("SELECT DISTINCT source FROM books ORDER BY 1")], [])
    term = request.args.get("q", "").strip()
    # searching by name shows every matching book (even if only 1 shop has it); otherwise only shared books
    min_shops = request.args.get("n", default=(1 if term else 2), type=int)
    where, params = ["u.n_sources >= %s"], [min_shops]
    if term:
        # match the unified title OR any shop's own title / author
        where.append("""(u.title ILIKE %s OR EXISTS (SELECT 1 FROM books x WHERE x.dedup_key = u.dedup_key
                          AND (x.title ILIKE %s OR x.author ILIKE %s)))""")
        params += [f"%{term}%"] * 3
    rows = safe(lambda: q(f"""
        SELECT u.dedup_key, u.title, u.author, u.isbn, u.n_sources, u.min_price, u.max_price,
               u.cheapest_source, (u.max_price - u.min_price) AS diff,
               json_object_agg(b.source, json_build_object('price', b.price, 'url', b.url)) AS offers
        FROM books_unified u JOIN books b USING (dedup_key)
        WHERE {" AND ".join(where)}
        GROUP BY u.dedup_key ORDER BY diff DESC, u.title LIMIT 500""", params), [])
    # who is cheapest how often + average price of the same matched books per shop
    wins = safe(lambda: q("""
        SELECT cheapest_source AS source, COUNT(*) AS n FROM books_unified
        WHERE n_sources >= %s GROUP BY 1 ORDER BY 2 DESC""", [min_shops]), [])
    avg_same = safe(lambda: q("""
        SELECT b.source, ROUND(AVG(b.price), 0) AS avg_price, COUNT(*) AS n
        FROM books b JOIN books_unified u USING (dedup_key)
        WHERE u.n_sources >= %s GROUP BY 1 ORDER BY 1""", [min_shops]), [])
    summary = safe(lambda: q("""
        SELECT COUNT(*) FILTER (WHERE n_sources >= 2) AS in2,
               COUNT(*) FILTER (WHERE n_sources >= 3) AS in3,
               ROUND(AVG(max_price - min_price) FILTER (WHERE n_sources >= 2), 0) AS avg_save,
               MAX(max_price - min_price) AS max_save
        FROM books_unified""")[0], {})
    return render_template("compare.html", rows=rows, srcs=srcs, wins=wins, avg_same=avg_same,
                           summary=summary, f={"n": min_shops, "q": term})


@app.route("/status")
def status():
    runs = safe(lambda: q("SELECT * FROM pipeline_runs ORDER BY started_at DESC NULLS LAST LIMIT 30"), [])
    quarantine = safe(lambda: q("""
        SELECT reason, source, COUNT(*) AS n, MAX(created_at) AS last
        FROM books_quarantine GROUP BY reason, source ORDER BY last DESC LIMIT 20"""), [])
    return render_template("status.html", runs=runs, quarantine=quarantine)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
