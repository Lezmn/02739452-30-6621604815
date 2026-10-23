# 02739452 Final — ระบบรวบรวมราคานิยายสืบสวนจากร้านหนังสือออนไลน์ไทย

**หัวข้อ:** ราคาหนังสือ — ขอบเขต: ราคานิยายแนวสืบสวนสอบสวน/ลึกลับ (Mystery) จากร้านหนังสือออนไลน์ไทย

Apache Airflow ดึงข้อมูลจาก 3 ร้าน **ขนานกัน** → แปลงเป็น schema เดียว → ตรวจคุณภาพ → ตัดรายการซ้ำข้ามร้าน → **UPSERT** ลง PostgreSQL → เว็บ dashboard (Flask) อ่านจาก PostgreSQL โดยตรง

## แหล่งข้อมูล

| # | แหล่ง | วิธีดึง | หน้าที่ใช้ |
|---|---|---|---|
| 1 | SE-ED https://www.se-ed.com | หน้าเว็บ render ด้วย JavaScript → เรียก JSON API สาธารณะที่หน้าเว็บใช้ (`mp-api.se-ed.com/web-bff/search-product`) ไม่ต้องมี token | หมวด นิยายสืบสวน ซ่อนเงื่อน สยองขวัญ (เฉพาะเล่มจริง) |
| (ปิดไว้) | Bookcaze https://www.bookcaze.com | web scraping (OpenCart HTML, เคารพ Crawl-delay 5 วิ) | ค้นคำ สืบสวน / ฆาตกรรม / ปริศนา / agatha / เชอร์ล็อก |
| 2 | B2S https://www.b2s.co.th | หน้าเว็บ render ด้วย JavaScript → เรียก catalog API ที่หน้าเว็บใช้ ด้วย guest token จาก `.env` (`B2S_API_TOKEN`) | หมวด นิยายสืบสวนสอบสวน |
| 3 | Amarinbooks https://amarinbooks.com | web scraping (WooCommerce HTML) | หมวด นิยายสืบสวน |

- ไม่ใช้ Selenium, ตรวจ `robots.txt` ทุก URL ก่อนดึง (`urllib.robotparser`), หน่วง 1.5 วินาทีระหว่างหน้า, ระบุ User-Agent ชัดเจน
- เก็บเฉพาะข้อมูลสินค้า (ชื่อเรื่อง ผู้แต่ง ราคา ISBN ลิงก์) **ไม่มีข้อมูลส่วนบุคคล** (PDPA)
- SE-ED และ B2S โหลดสินค้าด้วย JavaScript จึงหา API ที่หน้าเว็บเรียกผ่าน DevTools (Network → Fetch/XHR) แล้วเรียกตรงด้วย requests แทน Selenium; Amarinbooks เป็น HTML scraping จริง (Bookcaze มี parser แต่ปิดไว้); นายอินทร์ปิดไว้
- ต้องใส่ `B2S_API_TOKEN` ใน `.env` (ดูวิธีหาใน `.env.example`) ถ้าไม่ใส่ B2S จะ fail แต่ DAG ยังรวมแหล่งอื่นต่อได้
- เปลี่ยน/เพิ่ม URL หมวดได้ทาง `.env` (`SOURCE_BOOKCAZE_URLS` ฯลฯ) โดยไม่ต้องแก้โค้ด

## สถาปัตยกรรม DAG `mystery_books_pipeline`

```
create_tables → start_run → [TaskGroup sources]
                              ├─ seed:   extract → transform
                              ├─ b2s:    extract → transform     (รันขนาน)
                              └─ amarin: extract → transform
                           → merge (trigger_rule=all_done: แหล่งไหนล่มก็รวมที่เหลือต่อ)
                           → quality_check (branch)
                                ├─ ผ่าน   → load_postgres   (UPSERT books + books_unified)
                                └─ ไม่ผ่าน → quarantine_batch (เก็บลง books_quarantine)
                           → finalize_run (บันทึกสถานะลง pipeline_runs)
```

| ระดับ | สิ่งที่ทำ |
|---|---|
| 1 | extract → transform → load → PostgreSQL → เว็บตาราง + กราฟ |
| 2 | 3 แหล่งรันขนานใน TaskGroup, schema เดียว, `INSERT … ON CONFLICT (source, source_id) DO UPDATE` (รันซ้ำแถวไม่เพิ่ม), เว็บมี KPI 6 ตัว + ตัวกรอง (ร้าน/ช่วงราคา/ค้นหา/มีส่วนลด/เรียง) |
| 3 | `merge` ใช้ `TriggerRule.ALL_DONE` → แหล่งล่มก็ยังรวมที่เหลือได้; ตัดซ้ำข้ามร้านด้วย ISBN แล้ว fallback ชื่อเรื่องที่ normalize + fuzzy match (เลขเล่มต้องตรงกัน) → ตาราง `books_unified`; ตรวจคุณภาพรายแถว + `@task.branch` แตกเส้นทาง |
| โบนัส | หน้า `/status` แสดงสถานะ pipeline แต่ละรอบ สถานะแต่ละแหล่ง และสถิติ quarantine |

### ตาราง PostgreSQL (database `books`)
- `books` — 1 แถว/สินค้า/ร้าน, PK `(source, source_id)`
- `books_unified` — 1 แถว/หนังสือหลังตัดซ้ำข้ามร้าน (ราคาถูกสุด/แพงสุด/ร้านที่ถูกสุด)
- `books_quarantine` — แถวที่ไม่ผ่านการตรวจคุณภาพ พร้อมเหตุผล
- `pipeline_runs` — log ของแต่ละรอบ (หน้าสถานะ)

กฎคุณภาพ: ชื่อเรื่องต้องมี, ราคา 1–20,000 บาท, ไม่ซ้ำในร้านเดียวกัน; ทั้งชุดต้องผ่าน ≥ `MIN_VALID_RATIO` (ค่าเริ่ม 80%)

## วิธีรัน

```bash
cp .env.example .env          # แก้รหัสผ่าน (Linux: ตั้ง AIRFLOW_UID=$(id -u))
docker compose up -d --build
```
- Airflow: http://localhost:8080 (user/pass ตาม `.env`, ค่าเริ่ม admin/admin) → เปิด DAG `mystery_books_pipeline` → ▶ Trigger
- Dashboard: http://localhost:5000 (`/compare` เทียบราคาข้ามร้าน, `/status` สถานะ pipeline)
- PostgreSQL (DBeaver/psql): host `127.0.0.1` port `5433` database `books` user/pass ตาม `.env` (ค่าเริ่ม airflow/airflow) — ใช้ 5433 เพื่อไม่ชนกับ PostgreSQL ที่ติดตั้งในเครื่อง

ทดสอบ scraper อย่างเดียวโดยไม่ต้องใช้ Docker:
```bash
pip install requests beautifulsoup4 lxml
python scripts/probe.py            # ทุกแหล่ง หน้าแรก
python scripts/probe.py amarin 3   # แหล่งเดียว 3 หน้า
```

## โครงสร้าง
```
dags/mystery_books_dag.py   # DAG
dags/books/scraper.py       # ดึงหน้าเว็บ + robots.txt (+Crawl-delay) + parser (WooCommerce/OpenCart/JSON)
dags/books/transform.py     # normalize / validate / dedup
dags/books/db.py            # schema + UPSERT
dags/books/config.py        # URL ของแต่ละแหล่ง
web/                        # Flask dashboard (อ่าน PostgreSQL ตรง)
airflow/                    # Dockerfile ของ Airflow + requirements
initdb/                     # สร้าง database books
scripts/probe.py            # ทดสอบ scraper
```
