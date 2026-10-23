# 02739452 Final — ระบบรวบรวมราคานิยายสืบสวนจากร้านหนังสือออนไลน์ไทย

**หัวข้อ:** ราคาหนังสือ — ขอบเขต: ราคานิยายแนวสืบสวนสอบสวน/ลึกลับ (Mystery) จากร้านหนังสือออนไลน์ไทย

Apache Airflow ดึงข้อมูลจาก 3 ร้าน **ขนานกัน** → แปลงเป็น schema เดียว → ตรวจคุณภาพ → ตัดรายการซ้ำข้ามร้าน → **UPSERT** ลง PostgreSQL → เว็บ dashboard (Flask) อ่านจาก PostgreSQL โดยตรง

## แหล่งข้อมูล

| # | แหล่ง | วิธีดึง | หน้าที่ใช้ |
|---|---|---|---|
| 1 | SE-ED https://www.se-ed.com | web scraping (`requests` + BeautifulSoup อ่าน `__NEXT_DATA__`/JSON-LD/HTML) | หมวด สืบสวนสอบสวน/สยองขวัญ |
| 2 | B2S https://www.b2s.co.th | web scraping (`__NUXT_DATA__`/HTML card) | หมวด นิยายสืบสวนสอบสวน |
| 3 | Amarinbooks https://amarinbooks.com | web scraping (WooCommerce HTML) | หมวด นิยายสืบสวน |

- ไม่ใช้ Selenium, ตรวจ `robots.txt` ทุก URL ก่อนดึง (`urllib.robotparser`), หน่วง 1.5 วินาทีระหว่างหน้า, ระบุ User-Agent ชัดเจน
- เก็บเฉพาะข้อมูลสินค้า (ชื่อเรื่อง ผู้แต่ง ราคา ISBN ลิงก์) **ไม่มีข้อมูลส่วนบุคคล** (PDPA)
- เปลี่ยน/เพิ่ม URL หมวดได้ทาง `.env` (`SOURCE_SEED_URLS` ฯลฯ) โดยไม่ต้องแก้โค้ด

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
- PostgreSQL: localhost:5432 database `books`

ทดสอบ scraper อย่างเดียวโดยไม่ต้องใช้ Docker:
```bash
pip install requests beautifulsoup4 lxml
python scripts/probe.py            # ทุกแหล่ง หน้าแรก
python scripts/probe.py amarin 3   # แหล่งเดียว 3 หน้า
```

## โครงสร้าง
```
dags/mystery_books_dag.py   # DAG
dags/books/scraper.py       # ดึงหน้าเว็บ + robots.txt + parser
dags/books/transform.py     # normalize / validate / dedup
dags/books/db.py            # schema + UPSERT
dags/books/config.py        # URL ของแต่ละแหล่ง
web/                        # Flask dashboard (อ่าน PostgreSQL ตรง)
airflow/                    # Dockerfile ของ Airflow + requirements
initdb/                     # สร้าง database books
scripts/probe.py            # ทดสอบ scraper
```
