# HANDOFF — สำหรับ AI ตัวอื่นที่มาทำงานต่อ

## บริบท
- ข้อสอบปฏิบัติวิชา 02739452 (Big Data Platform) ม.เกษตรศาสตร์ กำแพงแสน, 23 ต.ค. 2569, 13:00–16:00 น. (ใช้ AI ได้)
- ส่ง: GitHub repo public ชื่อ `02739452-<ลำดับที่>-<รหัสนิสิต>` + PDF `<ลำดับที่>_<รหัสนิสิต>_summary.pdf` (≤3 หน้า) ภายใน 16:00
- repo ต้องมี `dags/`, `web/`, `docker-compose.yml`, `requirements.txt`, `README.md`, `.env.example` (ห้าม commit รหัสผ่าน)

## หัวข้อที่จอง
- หมวด: ราคาหนังสือ
- ขอบเขต: ราคานิยายแนวสืบสวนสอบสวน/ลึกลับ (Mystery) จากร้านหนังสือออนไลน์ไทย
- แหล่ง: 1) SE-ED https://www.se-ed.com 2) B2S https://www.b2s.co.th 3) นายอินทร์ https://www.naiin.com

## ข้อกำหนดโจทย์ (ย่อ)
- ระดับ1(30): 1 แหล่ง → DAG extract→transform→load → PostgreSQL → เว็บตาราง + กราฟ 1 กราฟ
- ระดับ2(20): ≥2 แหล่ง ขนานด้วย TaskGroup, schema เดียว, UPSERT (รันซ้ำแถวไม่เพิ่ม), เว็บมี KPI + ตัวกรอง
- ระดับ3(15): 3 แหล่ง, แหล่งล่มยังรวมที่เหลือได้, ตัดซ้ำข้ามแหล่ง, ตรวจคุณภาพแล้วแตกเส้นทาง (branch)
- โบนัส(+5): หน้าสถานะ pipeline หรือ Dynamic Task Mapping
- ต้อง web scraping ≥1 แหล่ง ห้าม Selenium, เคารพ robots.txt, ห้ามเก็บข้อมูลส่วนบุคคล, รวม ≥100 รายการ
- dashboard ต้องอ่านจาก PostgreSQL โดยตรง

## ข้อมูล robots.txt ที่ตรวจแล้ว
- se-ed.com: อนุญาต ยกเว้น /admin /login /cart /checkout ฯลฯ — เว็บเป็น Next.js (ข้อมูลน่าจะอยู่ใน `__NEXT_DATA__`)
- naiin.com: อนุญาต แต่ห้าม `/search-result`, `/api/v1`, `/livewire` — หน้าแรกโหลดสินค้าด้วย JS อาจต้องใช้หน้าหมวดหมู่
- b2s.co.th: เว็บเป็น Nuxt — ยังไม่ได้ตรวจ robots (โค้ดเช็ก robots ตอนรันอยู่แล้ว)

## สถานะงาน
ดูส่วน "STATUS" ท้ายไฟล์ (อัปเดตโดย AI ตัวล่าสุด)

## STATUS (อัปเดต 13:35)
แหล่งจริงที่ใช้: **SE-ED, B2S, Amarinbooks** (นายอินทร์บล็อกบอท → ปิดไว้ใน `ENABLED_SOURCES`)

เสร็จและทดสอบแล้ว (Airflow 2.10.5 + Postgres 16 ใน sandbox, ใช้ข้อมูลจำลองเพราะ sandbox เข้าเว็บร้านไม่ได้):
- [x] DAG `dags/mystery_books_dag.py` โหลดได้ไม่มี import error
- [x] TaskGroup 3 แหล่งขนาน, merge ALL_DONE (จำลอง B2S ล่ม → รวม 2 แหล่งที่เหลือ สถานะ partial)
- [x] quality branch → load_postgres / quarantine_batch
- [x] UPSERT รัน 2 รอบแถวไม่เพิ่ม, dedup ข้ามร้าน (ISBN → ชื่อ normalize + fuzzy, เลขเล่มต้องตรง)
- [x] เว็บ Flask `/`, `/compare`, `/status` ตอบ 200
- [x] docker-compose.yml ผ่าน `docker compose config`

ยังไม่ได้ยืนยัน (ต้องรันบนเครื่องผู้ใช้ที่มีอินเทอร์เน็ต):
- [ ] `python scripts/probe.py` ว่าแต่ละร้านดึงได้กี่รายการ — Amarin (WooCommerce) น่าจะได้แน่; SE-ED (Next.js `__NEXT_DATA__`) และ B2S (Nuxt 2, ใช้ HTML fallback) ยังไม่แน่ใจ
  - ถ้าได้ 0: เปิด view-source หน้าหมวด หา JSON/โครง HTML การ์ดสินค้า แล้วเพิ่ม parser เฉพาะใน `dags/books/scraper.py` (ดู `parse_woocommerce` เป็นตัวอย่าง) และตั้ง `"parser"` ใน `config.py`
  - pagination: SE-ED ใช้ `?page=`, B2S `?page=`, Amarin `/page/N/` — ถ้าไม่ถูกให้แก้ใน `config.py`
- [ ] `docker compose up -d --build` บนเครื่องจริง แล้ว trigger DAG
- [ ] ข้อมูลรวม ≥100 รายการ (เพิ่ม `max_pages` ใน config ถ้าไม่พอ)
- [ ] push GitHub (public) ชื่อ `02739452-<ลำดับ>-<รหัส>`, ทำ PDF จาก `docs/SUMMARY_DRAFT.md` + ภาพ Graph/Grid view + dashboard
