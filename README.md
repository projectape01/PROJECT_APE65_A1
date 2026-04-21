# PROJECT_APE65_A1

โปรเจกต์นี้เป็นระบบตรวจชิ้นงานด้วยกล้องและโมเดล YOLO/OpenVINO พร้อมหน้า Flask และแดชบอร์ด Streamlit

## โครงสร้างที่จัดระเบียบแล้ว

### Root

- `app.py` entrypoint หลักของระบบ Flask/inspection runtime
- `dashboard.py` หน้า dashboard สำหรับติดตามสถานะการผลิต
- `run_app.sh` สคริปต์เริ่มระบบ
- `smoke_test.py` สคริปต์ตรวจ endpoint หลักแบบไม่สตาร์ท worker thread ทั้งระบบ
- `requirements.txt` dependency ของ dashboard และเครื่องมือที่ใช้ร่วมกัน
- `config.json` ค่าตั้งค่าเครื่อง local

### Source Modules

- `core/`
  ไฟล์ config และ runtime defaults ที่ใช้ร่วมกัน
- `routes/`
  Flask route registration
- `services/`
  integration/service logic เช่น HTTP helper และ printer MQTT service
- `utils/`
  stateless helper functions เช่น inspection rules และ system helpers

### UI And Assets

- `templates/`
  Flask templates ที่ runtime ใช้งานจริง
- `static/`
  โลโก้, model assets และไฟล์ static สำหรับหน้าเว็บ

### Runtime Data

- `captures/`
  รูปที่บันทึกจากงาน inspection
- `logs/`
  ไฟล์ log ทั้งหมด
- `tmp/`
  ไฟล์ชั่วคราวระหว่าง runtime รวมถึง output สำหรับ train/preview บางงาน

### Models And Archives

- `best_openvino_model/`
  โมเดลที่ runtime ใช้งานจริง
- `best.pt`
  ไฟล์โมเดลต้นฉบับ
- `archives/`
  ไฟล์ archive และ backup ที่ไม่ใช่ runtime หลัก

### Tools

- `tools/debug/`
  สคริปต์ช่วย debug ที่ไม่ควรปะปนกับ source runtime

## หมายเหตุการจัดระเบียบ

- helper modules ถูกย้ายออกจาก root ไปอยู่ในโฟลเดอร์ตามหน้าที่ เพื่อลดความรกและแยกความรับผิดชอบให้ชัดขึ้น
- `app.py`, `dashboard.py`, `run_app.sh` และ `smoke_test.py` ยังอยู่ root เพื่อให้การใช้งานเดิมไม่เปลี่ยน
- ไฟล์ backup และ debug scripts ถูกย้ายออกจากตำแหน่งที่ปะปนกับ runtime หลัก
- cache และ output ชั่วคราวที่ generate เอง เช่น `__pycache__/`, preview/debug images, smoke outputs และ temporary import artifacts สามารถล้างทิ้งได้เมื่อไม่ใช้งาน


## ข้อควรรู้

- ตอนนี้ `app.py` ใช้โมเดลจาก `best_openvino_model/`
- Runtime หลักใช้งาน inspection flow แค่ `SIDE1` และ `SIDE2` ส่วน `SIDE3` ถูกปิดไว้ชั่วคราว
- สามารถสลับ AI runtime ได้จาก `config.json` หรือ environment โดยใช้คีย์:
  - `AI_MODEL_PATH`
  - `AI_MODEL_TASK`
  - `AI_IMGSZ`
  - `AI_BASE_CONF`
- `captures/`, `logs/`, `tmp/`, `config.json`, log files และ virtualenv เป็นไฟล์/โฟลเดอร์ local runtime ไม่ควรเอาขึ้น git

ตัวอย่างใน `config.json`:

```json
{
  "AI_MODEL_PATH": "/home/ape01/PROJECT_APE65_A1/best_openvino_model",
  "AI_MODEL_TASK": "obb",
  "AI_IMGSZ": 640,
  "AI_BASE_CONF": 0.1
}
```
