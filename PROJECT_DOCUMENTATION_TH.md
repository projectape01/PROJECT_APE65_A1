# PROJECT_APE65_A1 - เอกสารสรุประบบตรวจสอบคุณภาพชิ้นงานอัตโนมัติ

เอกสารนี้สรุปภาพรวมทั้งหมดของโปรเจค `PROJECT_APE65_A1` เพื่อให้อ่านไฟล์เดียวแล้วเข้าใจว่าโปรเจคนี้ทำอะไร ใช้เทคโนโลยีอะไร หลักการทำงานเป็นอย่างไร และแต่ละส่วนเชื่อมต่อกันอย่างไร

## 1. ภาพรวมโปรเจค

`PROJECT_APE65_A1` เป็นระบบตรวจสอบคุณภาพชิ้นงานจากกระบวนการ 3D Printing แบบอัตโนมัติ โดยใช้กล้อง, AI, Computer Vision, Dashboard, Database และ LINE OA เพื่อช่วยตรวจสอบว่าแต่ละชิ้นงานผ่านหรือไม่ผ่านตามเงื่อนไขที่กำหนด

แนวคิดหลักของระบบคือ:

- ใช้กล้อง Raspberry Pi Camera เก็บภาพชิ้นงานแบบ Real-time
- ใช้ AI ช่วยจำแนกด้านของชิ้นงานและตรวจ defect
- ใช้ OpenCV วัดขนาดชิ้นงานใน `SIDE 3`
- เก็บผลตรวจลง Supabase
- แสดงสถานะและผลผลิตผ่าน Dashboard
- แจ้งเตือน NG และตอบคำสั่งผ่าน LINE OA
- เชื่อมต่อกับ Bambu Lab A1, TM Cobot และ Raspberry Pi เพื่อทำงานใน workflow อัตโนมัติ

ระบบนี้ออกแบบให้รองรับการตรวจชิ้นงาน 3 ด้าน:

- `SIDE 1` ตรวจด้วย AI และ YOLO
- `SIDE 2` ตรวจด้วย AI และ YOLO
- `SIDE 3` ตรวจวัดขนาดด้วย OpenCV Measurement

## 2. เป้าหมายของระบบ

เป้าหมายของโปรเจคคือสร้างระบบตรวจสอบคุณภาพที่สามารถทำงานร่วมกับกระบวนการผลิตจริงได้ โดยลดการตรวจด้วยคนและเพิ่มความต่อเนื่องของข้อมูลการผลิต

สิ่งที่ระบบทำได้:

- ตรวจชิ้นงานทีละชิ้น
- แยกขั้นตอนการตรวจเป็น `SIDE 1`, `SIDE 2`, `SIDE 3`
- ระบุผล `GOOD` หรือ `NG`
- ตรวจ defect และตีกรอบตำแหน่ง defect
- วัดขนาด `TOP`, `BOTTOM`, `LENGTH`
- ตัดสินว่าค่าขนาดอยู่ใน tolerance หรือไม่
- บันทึกภาพและข้อมูลลงฐานข้อมูล
- สรุปผลผ่าน Dashboard
- แจ้งเตือนผ่าน LINE OA
- ค้นหาข้อมูลย้อนหลังจาก `Part ID`

## 3. เทคโนโลยีที่ใช้

### 3.1 Python

Python เป็นภาษาหลักของระบบ ใช้สำหรับ:

- ควบคุม Flask web server
- ประมวลผลภาพด้วย OpenCV
- รัน AI inference ด้วย Ultralytics YOLO/OpenVINO
- ติดต่อ Supabase REST API
- ติดต่อ LINE Messaging API
- อ่านสถานะ Raspberry Pi
- เชื่อมต่อ Printer ผ่าน MQTT
- เปิด Modbus server สำหรับสื่อสารกับ automation workflow

ไฟล์หลักคือ:

- `app.py`
- `routes/app_routes.py`
- `dashboard.py`
- `utils/side3_measurement.py`
- `services/printer_service.py`

### 3.2 Flask

Flask ใช้เป็น web application หลักสำหรับหน้า Inspection System

หน้าที่ของ Flask:

- แสดงหน้า Live Feed
- ส่งภาพกล้องแบบ stream
- รับคำสั่งจากหน้า UI
- จัดการ workflow การตรวจ
- เปิด endpoint สำหรับ LINE webhook ฝั่ง local
- เปิด API สำหรับ dashboard หรือ frontend ดึงสถานะ

ไฟล์ที่เกี่ยวข้อง:

- `app.py`
- `routes/app_routes.py`
- `templates/index.html`

### 3.3 Streamlit

Streamlit ใช้ทำ Dashboard สำหรับ Production Monitor

หน้าที่ของ Dashboard:

- แสดงภาพรวมการผลิต
- แสดงข้อมูล Part ล่าสุด
- แสดงจำนวน GOOD / NG
- แสดง Yield
- แสดง Dimension Control Chart
- แสดงสถานะเครื่องจักร เช่น Raspberry Pi, Bambu Lab A1, TM Cobot, Database
- ดึงข้อมูลจาก Supabase มาแสดง

ไฟล์หลัก:

- `dashboard.py`

### 3.4 OpenCV

OpenCV ใช้สำหรับ Computer Vision และระบบวัดขนาด `SIDE 3`

งานที่ OpenCV ทำในโปรเจคนี้:

- อ่านภาพจากกล้อง
- แปลงสีภาพ
- แยกชิ้นงานออกจากพื้นหลัง
- หา contour ของชิ้นงาน
- สร้าง bounding box
- วาดเส้นวัดบน Live Feed
- คำนวณระยะ pixel แล้วแปลงเป็น millimeter
- ทำ calibration preview
- วาด overlay เช่น contour, เส้นวัด, label, ค่า mm

ไฟล์หลัก:

- `utils/side3_measurement.py`
- `app.py`

### 3.5 YOLO / Ultralytics / OpenVINO

YOLO ใช้ตรวจจับ defect หรือ label บนชิ้นงาน โดยโมเดลถูกโหลดผ่าน Ultralytics และ runtime สามารถใช้ OpenVINO model ได้

หน้าที่ของ YOLO:

- ตรวจภาพจากกล้อง
- หาตำแหน่ง defect
- ให้ confidence score
- ส่งผลให้ระบบตัดสินว่าเป็น `GOOD` หรือ `NG`
- วาดกรอบ defect บนภาพ capture

ไฟล์และโฟลเดอร์ที่เกี่ยวข้อง:

- `best_openvino_model/`
- `best.pt`
- `app.py`
- `utils/inspection_utils.py`

หมายเหตุ: ไฟล์โมเดลจริงไม่ถูกอัปโหลดขึ้น GitHub เพราะเป็นไฟล์ใหญ่และเป็น runtime asset

### 3.6 Teachable Machine / Side Classifier

ระบบมีแนวคิดให้ AI ด้านหน้าใช้จำแนกว่าชิ้นงานอยู่ด้านไหน เช่น `SIDE 1`, `SIDE 2`, `SIDE 3` ก่อนส่งต่อให้ YOLO หรือ OpenCV ทำงานต่อ

หลักการที่ใช้:

- ใช้ภาพกล้องจริงเป็น input
- จำแนก side จากลักษณะของชิ้นงาน
- เมื่อตรวจเจอ side ที่ถูกต้อง ระบบจึงค่อยเปิดขั้นตอนถัดไป

แนวคิดที่ผู้ใช้ต้องการคือ:

- TM หรือ side classifier ทำหน้าที่บอกว่าเป็น side ไหน
- YOLO ทำหน้าที่ตรวจ defect เฉพาะ `SIDE 1/2`
- OpenCV ทำหน้าที่วัดขนาดเฉพาะ `SIDE 3`

### 3.7 Supabase

Supabase ใช้เป็น backend cloud database และ storage

หน้าที่ของ Supabase:

- เก็บข้อมูล inspection แต่ละ part
- เก็บสถานะระบบ
- เก็บ subscriber ของ LINE OA
- เก็บ URL ภาพ capture
- ให้ Edge Function ตอบ LINE OA ได้แม้ Raspberry Pi ปิดอยู่

ตารางสำคัญ:

- `part_records`
- `line_subscribers`

### 3.8 Supabase Edge Function

ใช้สำหรับ LINE Bot ที่รันบน Supabase แทนการรันบน Raspberry Pi โดยตรง

ข้อดี:

- LINE OA ยังตอบคำสั่งได้แม้ Raspberry Pi ปิด
- ไม่ต้องพึ่ง ngrok ตลอดเวลา
- ดึงข้อมูลจาก Supabase ได้โดยตรง
- เหมาะกับคำสั่ง `status`, `summary`, `recent`, `part <id>`, `information`

ไฟล์หลัก:

- `supabase/functions/line-bot/index.ts`

### 3.9 LINE OA / LINE Messaging API

LINE OA ใช้เป็นช่องทางแจ้งเตือนและสั่งดูข้อมูล

สิ่งที่ทำได้:

- แจ้งเตือน NG Alert
- แจ้งเตือน System Alert
- ตอบคำสั่ง `status`
- ตอบคำสั่ง `summary`
- ตอบคำสั่ง `recent`
- ตอบคำสั่ง `part <id>`
- ตอบคำสั่ง `information`
- จัดการ subscriber ด้วย `subscribe`, `unsubscribe`, `subscribers`
- ส่ง Flex Message ที่ตกแต่งสวยงาม
- ส่งภาพ capture ของชิ้นงาน

### 3.10 Bambu Lab A1

Bambu Lab A1 เป็น 3D Printer ที่ระบบติดตามสถานะผ่าน printer service

ข้อมูลที่ระบบสนใจ:

- printer online/offline
- print progress
- print status
- task/current job

ไฟล์หลัก:

- `services/printer_service.py`
- `app.py`
- `dashboard.py`

### 3.11 TM Cobot / Modbus

ระบบมี Modbus server เพื่อส่งสัญญาณให้ automation workflow หรือ cobot อ่านได้

แนวคิด:

- ระบบ inspection ทำงานเสร็จ
- ส่ง signal ผ่าน Modbus
- TM Flow หรือระบบ robot นำ signal ไปใช้ตัดสิน workflow ถัดไป

ไฟล์หลัก:

- `app.py`

## 4. Architecture ภาพรวม

โครงสร้างการทำงานแบบย่อ:

```text
Camera
  |
  v
Flask App / Inspection Runtime
  |
  |-- SIDE 1/2 -> AI Side Classifier -> YOLO Defect Detection
  |
  |-- SIDE 3 -> OpenCV Measurement
  |
  |-- Capture Image
  |
  |-- Save Result
  v
Supabase Database + Storage
  |
  |-- Dashboard reads data
  |
  |-- LINE Edge Function reads data
  |
  v
LINE OA / Production Monitor
```

ระบบแบ่งออกเป็น 5 ส่วนใหญ่:

1. Inspection Runtime
2. AI / Computer Vision
3. Database / Storage
4. Dashboard
5. LINE Notification / Chatbot

## 5. Workflow การตรวจชิ้นงาน

### 5.1 เริ่มต้นระบบ

เมื่อเปิดระบบ:

- Flask app เริ่มทำงาน
- กล้องเริ่มส่งภาพ
- โหลด AI model
- เตรียมสถานะ runtime
- ตรวจสถานะ Printer / Cobot / Database
- Dashboard และ LINE สามารถอ่านข้อมูลได้

### 5.2 System Ready

ระบบจะรอให้ผู้ใช้หรือ workflow กด `System Ready / Next Part`

เมื่อพร้อม:

- ระบบสร้างหรือจอง `Part ID`
- reset session ของ part ปัจจุบัน
- เริ่มตรวจ `SIDE 1`

### 5.3 SIDE 1 Inspection

ใน `SIDE 1`:

- กล้องจับภาพชิ้นงาน
- AI ตรวจว่าภาพนิ่งและพร้อมตรวจ
- ระบบจำแนก side
- YOLO ตรวจ defect
- ถ้าพบ defect จะตีกรอบ
- บันทึกผลเป็น `GOOD_1` หรือ `NG_1`
- บันทึก capture ของ SIDE 1

### 5.4 SIDE 2 Inspection

ใน `SIDE 2`:

- ผู้ใช้หรือ robot เปลี่ยนชิ้นงานเป็นด้านที่สอง
- ระบบรอให้ภาพนิ่ง
- ตรวจ side ให้มั่นใจก่อน
- YOLO ตรวจ defect
- บันทึกผลเป็น `GOOD_2` หรือ `NG_2`
- บันทึก capture ของ SIDE 2

### 5.5 SIDE 3 Measurement

ใน `SIDE 3`:

- ระบบต้องยืนยันว่าชิ้นงานถูกเปลี่ยนเป็น `SIDE 3` แล้ว
- ภาพต้องนิ่งก่อนเริ่มวัด
- OpenCV ตรวจ contour ของชิ้นงาน
- วาดเส้นวัดบน Live Feed
- แสดงค่าบนภาพก่อนส่งเข้า UI
- นำค่า `TOP`, `BOTTOM`, `LENGTH` ไปแสดงในกล่อง `SIDE 3 MEASUREMENT`
- ตรวจค่าเทียบกับ tolerance
- บันทึก capture ของ SIDE 3

### 5.6 Final Result

ระบบตัดสินผลรวม:

- ถ้า `SIDE 1`, `SIDE 2`, `SIDE 3` ผ่านทั้งหมด ผลเป็น `GOOD`
- ถ้ามี side ใด side หนึ่ง fail ผลเป็น `NG`
- ถ้าขนาดเกิน tolerance ผลเป็น `NG`
- ถ้า YOLO พบ defect ผลเป็น `NG`

จากนั้นระบบบันทึกข้อมูลลง Supabase

## 6. หลักการ AI ที่ใช้

### 6.1 Classification

Classification คือการจำแนกว่า input image อยู่ในกลุ่มใด เช่น:

- SIDE 1
- SIDE 2
- SIDE 3
- UNKNOWN

ในระบบนี้ classification ใช้เพื่อช่วย workflow ว่าตอนนี้ควรทำขั้นตอนไหน

ข้อดี:

- ลดการตรวจผิด side
- ป้องกันการข้ามขั้นตอน
- ช่วยให้ระบบรู้ว่าควรเปิด YOLO หรือ OpenCV เมื่อไร

### 6.2 Object Detection

Object Detection คือการหาว่าในภาพมีวัตถุหรือ defect อยู่ตรงไหน โดยผลลัพธ์มักประกอบด้วย:

- class label
- bounding box
- confidence score

ในโปรเจคนี้ YOLO ใช้ตรวจ defect บน `SIDE 1/2`

### 6.3 Confidence Score

Confidence คือค่าความมั่นใจของโมเดล เช่น 0.83 หมายถึงโมเดลมั่นใจ 83%

ระบบไม่ควรเชื่อ AI ทันทีทุก frame เพราะอาจมี noise จึงต้องมีเงื่อนไขเสริม เช่น:

- ภาพต้องนิ่ง
- confidence ต้องเกิน threshold
- label ต้องสอดคล้องกับ side ที่กำลังตรวจ
- ต้องไม่ยืนยัน `GOOD_3` จนกว่าจะเข้าสู่ `SIDE 3` จริง

### 6.4 Stable Frame

Stable Frame คือหลักการตรวจว่าภาพนิ่งแล้วหรือยัง

แนวคิด:

- เปรียบเทียบ frame ปัจจุบันกับ frame ก่อนหน้า
- ถ้าความต่างน้อย แสดงว่าภาพนิ่ง
- ต้องนิ่งต่อเนื่องหลาย frame ก่อนเริ่ม inference หรือ measurement

ประโยชน์:

- ลดค่ากระพริบ
- ลดการจับผิดตอนมือกำลังขยับชิ้นงาน
- ลดการวัดผิดตอนชิ้นงานยังไม่อยู่ตำแหน่ง

## 7. หลักการ YOLO ในระบบนี้

YOLO ย่อมาจาก `You Only Look Once` เป็น object detection model ที่ตรวจภาพทั้งภาพในรอบเดียวแล้วทำนายตำแหน่งวัตถุ

หลักการโดยสรุป:

- รับภาพ input
- แบ่งพื้นที่หรือใช้ feature map เพื่อหาวัตถุ
- ทำนาย bounding box
- ทำนาย class
- ให้ confidence score
- ใช้ Non-Maximum Suppression ลดกรอบซ้ำ

ในโปรเจคนี้ YOLO ถูกใช้เพื่อ:

- ตรวจ defect
- ช่วยยืนยัน `GOOD/NG`
- ตีกรอบ defect บนภาพ
- เก็บภาพที่มี overlay เพื่อใช้ตรวจย้อนหลัง

ข้อควรระวัง:

- ถ้า training data ไม่ครอบคลุม โมเดลจะสับสน
- ถ้าแสงเปลี่ยนมาก ผลอาจเปลี่ยน
- ถ้า background หรือมุมกล้องไม่เหมือนตอน train ความแม่นยำจะลดลง
- ถ้า defect เล็กมากต้องมี resolution และ dataset ที่เหมาะสม

## 8. หลักการ OpenCV Measurement

ระบบวัดขนาด `SIDE 3` ใช้ Computer Vision ไม่ใช่ AI detection เป็นหลัก

แนวคิดการวัด:

1. รับภาพจากกล้อง
2. แยกชิ้นงานออกจากพื้นหลัง
3. หา contour ของชิ้นงาน
4. สร้างกรอบอ้างอิง
5. หาเส้นวัด `TOP`, `BOTTOM`, `LENGTH`
6. วัดระยะเป็น pixel
7. แปลง pixel เป็น millimeter
8. เทียบกับ target และ tolerance

### 8.1 Contour

Contour คือเส้นขอบของวัตถุที่ตรวจเจอในภาพ

ในระบบนี้ contour ใช้เพื่อ:

- หาขอบชิ้นงาน
- วาดเส้นสีเขียวตามรูปร่างชิ้นงาน
- ใช้เป็นข้อมูลอ้างอิงในการวัด

ข้อดี:

- เหมาะกับการหาขอบวัตถุ
- ไม่ต้อง train model
- ปรับ threshold และ morphology ได้

ข้อจำกัด:

- ถ้าพื้นหลังใกล้สีชิ้นงานเกินไป อาจจับพื้นหลังแทน
- ถ้าแสงสะท้อนสูง contour อาจขาดหรือเกิน
- ถ้าวัตถุโลหะสะท้อนแสง ต้องควบคุม lighting ให้ดี

### 8.2 Bounding Box

Bounding box คือกรอบล้อมรอบชิ้นงาน

ในระบบมีทั้ง:

- กรอบอ้างอิงแกนภาพ
- กรอบหมุนตามชิ้นงาน
- เส้น contour จริง

แต่ละแบบเหมาะกับงานต่างกัน:

- กรอบตามแกนภาพเหมาะกับวัตถุวางตรง
- กรอบหมุนเหมาะกับวัตถุเอียง
- contour เหมาะกับรูปร่างจริงของชิ้นงาน

### 8.3 Pixel to Millimeter

กล้องวัดได้เป็น pixel แต่ค่าที่ต้องการคือ millimeter

จึงต้องมี scale:

```text
mm = pixel * scale_mm_per_pixel
```

ค่า scale ได้จาก calibration หรือค่าที่ตั้งไว้ใน config

ตัวอย่าง:

```text
SIDE3_SCALE_MM_PER_PIXEL = 0.1025
```

ถ้าวัด pixel ได้ 500 px:

```text
500 * 0.1025 = 51.25 mm
```

### 8.4 Tolerance

Tolerance คือค่าความคลาดเคลื่อนที่ยอมรับได้

ค่าปัจจุบันของ `SIDE 3`:

```text
TOP    = 19.50 ± 0.3 mm
BOTTOM = 24.50 ± 0.3 mm
LENGTH = 90.00 ± 0.3 mm
```

เงื่อนไข:

```text
abs(measured_value - target_value) <= tolerance
```

ถ้าอยู่ในช่วงนี้คือผ่าน ถ้าเกินคือไม่ผ่าน

### 8.5 Smoothing

ค่าที่วัดจากภาพจริงอาจไม่นิ่ง เพราะ:

- noise จากกล้อง
- แสงเปลี่ยน
- contour สั่น
- ชิ้นงานขยับเล็กน้อย
- threshold เปลี่ยนตามภาพ

ระบบจึงมี smoothing เพื่อลดการกระพริบของค่า

แนวคิด:

```text
smoothed = previous * (1 - alpha) + current * alpha
```

ค่า alpha ยิ่งน้อย ค่ายิ่งนิ่งแต่ตอบสนองช้า

## 9. ระบบวัด SIDE 3 ปัจจุบัน

ค่าที่ระบบวัด:

- `TOP`
- `BOTTOM`
- `LENGTH`

สีเส้นที่ใช้ใน Live Feed:

- contour: สีเขียว
- bounding/part axis: สีเหลือง
- `LENGTH`: สีแดงเข้ม
- `BOTTOM`: สีม่วง
- `TOP`: สีน้ำเงิน

ค่าจะถูกแสดง:

- บน Live Feed บริเวณปลายเส้นวัด
- ในกล่อง `SIDE 3 MEASUREMENT`
- ใน Supabase record
- ใน Dashboard
- ใน LINE Alert หาก part นั้นเป็น NG

## 10. Calibration

Calibration คือการปรับ scale การวัดให้ตรงกับขนาดจริง

หลักการ:

1. ใช้วัตถุมาตรฐานที่รู้ขนาดแน่นอน
2. วัดวัตถุนั้นด้วยระบบ
3. เทียบค่าที่ระบบวัดได้กับค่าจริง
4. คำนวณ scale หรือ offset ใหม่
5. นำ scale ไปใช้กับการวัดชิ้นงานจริง

วัตถุที่เคยใช้เป็น reference:

- Gage box ขนาด `75 x 35 x 9 mm`

ข้อควรระวังของ calibration:

- วัตถุมาตรฐานควรมีขอบชัด
- พื้นหลังควรตัดกับวัตถุ
- แสงต้องนิ่ง
- ระยะกล้องต้องคงที่
- มุมกล้องต้องไม่เปลี่ยน
- ถ้าใช้โลหะ อาจมีแสงสะท้อนทำให้ contour ผิด

## 11. Database Design

ตารางหลักคือ `part_records`

ข้อมูลที่เก็บโดยรวม:

- `part_id`
- `record_timestamp`
- `side1`
- `side2`
- `side3`
- `result`
- `dimension of top`
- `dimension of bottom`
- `dimension of length`
- `defect_s1`
- `defect_s2`
- `defect_s3`
- `capture_s1`
- `capture_s2`
- `capture_s3`

แนวคิดการเก็บข้อมูล:

- หนึ่งแถวต่อหนึ่งชิ้นงาน
- แต่ละชิ้นงานมีผลตรวจ 3 side
- มีผลรวม `GOOD/NG`
- มีค่าขนาดของ `SIDE 3`
- มี URL รูป capture สำหรับตรวจย้อนหลัง

## 12. Dashboard

Dashboard คือหน้าสรุปผลการผลิตและสถานะระบบ

ข้อมูลที่แสดง:

- Total inspected
- GOOD
- NG
- Yield %
- Inspection Overview
- Part detail
- Dimension value
- Dimension Control Chart
- Status ของ Raspberry Pi
- Status ของ Bambu Lab A1
- Status ของ TM Cobot
- Status ของ Database

### 12.1 Dimension Control Chart

Control Chart ใช้ดูแนวโน้มค่าขนาดของชิ้นงาน

ประโยชน์:

- เห็นว่าค่าขนาดเริ่ม drift หรือไม่
- เห็น part ที่หลุด tolerance
- ใช้ดู stability ของกระบวนการผลิต

แกน X ใช้ `Part ID`

แกน Y ใช้ค่า dimension เช่น:

- TOP
- BOTTOM
- LENGTH

## 13. LINE OA

LINE OA เป็นระบบแจ้งเตือนและ chatbot

คำสั่งที่รองรับ:

```text
status
summary
recent
part <id>
information
subscribe
unsubscribe
subscribers
```

### 13.1 status

แสดงสถานะระบบ:

- Raspberry Pi
- Bambu Lab A1
- TM Cobot
- Database
- Overall System

### 13.2 summary

สรุปผลการตรวจทั้งหมด:

- Total inspected
- GOOD
- NG
- Yield %
- Latest date/time
- Part range

### 13.3 recent

แสดงชิ้นงานล่าสุด:

- Part ID
- Result
- Side result
- Dimension
- Capture image buttons

### 13.4 part <id>

ค้นหาข้อมูลย้อนหลังจาก Part ID เช่น:

```text
part 12
```

ระบบจะส่งข้อมูล part นั้นในรูปแบบเดียวกับ `recent`

### 13.5 information

แสดงข้อมูลโปรเจค เช่น:

- ชื่อโปรเจค
- ผู้จัดทำ
- อาจารย์ที่ปรึกษา
- build/version

### 13.6 subscribe / unsubscribe

ใช้จัดการผู้รับแจ้งเตือน

- `subscribe` เพิ่มผู้ใช้เข้า subscriber list
- `unsubscribe` ปิดรับแจ้งเตือน
- `subscribers` แสดงจำนวน subscriber

### 13.7 NG Alert

เมื่อพบ NG ระบบส่ง alert ทันที

ข้อมูลที่ส่ง:

- Part ID
- Time
- Result
- Side ที่ fail
- Defect ที่พบ
- ค่า TOP / BOTTOM / LENGTH ถ้ามี
- รูป capture ทั้ง 3 side ถ้ามี

### 13.8 System Alert

แจ้งสถานะระบบ เช่น:

- Raspberry Pi ONLINE/OFFLINE
- Bambu Lab A1 ONLINE/OFFLINE
- TM Cobot ONLINE/OFFLINE
- Database ONLINE/OFFLINE

## 14. เหตุผลที่ย้าย LINE Bot ไป Supabase Edge Function

ตอนแรก LINE webhook สามารถรันบน Raspberry Pi ผ่าน Flask/ngrok ได้ แต่มีข้อจำกัด:

- ถ้า Pi ปิด LINE bot จะตอบไม่ได้
- ngrok อาจหลุดหรือ URL เปลี่ยน
- ต้องเปิด service ตลอด

จึงย้าย command chatbot ไป Supabase Edge Function

ข้อดี:

- ใช้งานได้แม้ Pi ปิด
- LINE webhook เสถียรกว่า
- ดึงข้อมูลจาก Supabase โดยตรง
- เหมาะกับ command ที่เป็น read-only เช่น `status`, `summary`, `recent`, `part`

## 15. ระบบ Capture Image

ระบบบันทึกภาพของแต่ละ side:

- `capture_s1`
- `capture_s2`
- `capture_s3`

รูป capture ใช้สำหรับ:

- ตรวจย้อนหลัง
- ส่งใน LINE Alert
- แสดงใน LINE command `recent` และ `part <id>`
- ใช้ดูตำแหน่ง defect ที่ถูกตีกรอบ

ภาพ runtime ไม่ถูกอัปโหลด GitHub เพราะเป็นข้อมูลการผลิตจริงและมีจำนวนมาก

## 16. ระบบ Status

ระบบติดตามสถานะหลายส่วน:

### 16.1 Raspberry Pi

ข้อมูลที่ตรวจ:

- CPU load
- RAM
- Disk
- Temperature
- timestamp ล่าสุด

ถ้าข้อมูล stale หรือ Pi ไม่ส่งข้อมูลใหม่ ระบบถือว่า offline

### 16.2 Bambu Lab A1

สถานะ printer มาจาก printer service / MQTT

ข้อมูลที่สนใจ:

- online/offline
- print progress
- current task
- printer status

### 16.3 TM Cobot

ตรวจจากสถานะ connection หรือ signal ที่ระบบรับรู้

### 16.4 Database

ตรวจจากการเรียก Supabase API

ถ้า query สำเร็จถือว่า online

## 17. โครงสร้างไฟล์สำคัญ

```text
PROJECT_APE65_A1/
  app.py
  dashboard.py
  run_app.sh
  requirements.txt
  config.example.json
  core/
  routes/
  services/
  utils/
  templates/
  static/
  supabase/
  deploy/
  tools/
```

### 17.1 app.py

เป็น runtime หลักของระบบ inspection

หน้าที่:

- เปิด Flask app
- จัดการกล้อง
- โหลด YOLO
- จัดการ workflow ตรวจชิ้นงาน
- จัดการ SIDE 3 measurement
- บันทึกผลไป Supabase
- ส่ง LINE Alert
- Monitor system status
- Modbus integration

### 17.2 routes/app_routes.py

รวม endpoint ของ Flask

หน้าที่:

- API ให้ frontend
- LINE webhook local
- status endpoint
- command endpoint
- calibration endpoint
- capture endpoint

### 17.3 templates/index.html

หน้า UI หลักของ Inspection System

หน้าที่:

- แสดง Live Feed
- แสดง workflow side inspection
- แสดง SIDE 3 Measurement
- แสดง Calibration controls
- แสดง Real-time AI Sensor
- รับ input จากผู้ใช้

### 17.4 utils/side3_measurement.py

ระบบวัดขนาดด้วย OpenCV

หน้าที่:

- หา contour
- คำนวณ measurement geometry
- วาด overlay
- คำนวณ TOP/BOTTOM/LENGTH
- calibration preview

### 17.5 dashboard.py

หน้า Production Monitor

หน้าที่:

- อ่านข้อมูล Supabase
- แสดง metric
- แสดง chart
- แสดง inspection history
- แสดง status system

### 17.6 supabase/functions/line-bot/index.ts

LINE Bot ที่รันบน Supabase Edge Function

หน้าที่:

- รับ webhook จาก LINE
- verify signature
- อ่านข้อมูลจาก Supabase
- สร้าง Flex Message
- ตอบ command

## 18. GitHub และการจัดการไฟล์

โปรเจคถูกเตรียมขึ้น GitHub โดยคัดเฉพาะไฟล์จำเป็น

ไฟล์ที่อัปโหลด:

- source code
- template
- requirements
- migration
- config example
- logo ที่ระบบใช้งานจริง

ไฟล์ที่ไม่อัปโหลด:

- `config.json`
- token/secret
- captures
- logs
- tmp
- model files
- calibration images
- virtual environment
- debug scripts ที่มีข้อมูลเฉพาะเครื่อง

เหตุผล:

- ลดขนาด repository
- ป้องกันข้อมูลลับรั่ว
- ป้องกันข้อมูล production ปะปนกับ source code
- ทำให้ repo clone ได้ง่าย

## 19. ข้อควรระวังด้าน Security

ห้ามอัปโหลดข้อมูลเหล่านี้ขึ้น GitHub:

- LINE Channel Access Token
- LINE Channel Secret
- Supabase Service Role Key
- Bambu Access Code
- Printer Serial Number
- `config.json`
- รูป capture ของงานจริง
- token ที่เคย paste ใน chat

ถ้า token หลุด:

- revoke token ทันที
- สร้าง token ใหม่
- อย่า commit token ลง repo

## 20. ข้อจำกัดและปัจจัยที่มีผลต่อความแม่นยำ

### 20.1 แสง

แสงมีผลมากกับ OpenCV และ AI

ผลกระทบ:

- contour ผิด
- defect ไม่ชัด
- confidence ลด
- ค่า measurement ไม่นิ่ง

แนวทาง:

- ใช้แสงคงที่
- ลดเงา
- ลดแสงสะท้อน
- ใช้ background ที่ตัดกับชิ้นงาน

### 20.2 ตำแหน่งกล้อง

ถ้ากล้องขยับ scale จะเปลี่ยน

ผลกระทบ:

- ค่าขนาดเพี้ยน
- calibration ใช้ไม่ได้
- contour เปลี่ยน

แนวทาง:

- fix กล้องให้แน่น
- ห้ามซูมหรือเปลี่ยน lens position หลัง calibration
- calibration ใหม่เมื่อเปลี่ยนระยะกล้อง

### 20.3 Dataset

AI จะดีเท่ากับ dataset ที่ train

ถ้า dataset ไม่ครอบคลุม:

- วาง SIDE 2 แล้วขึ้น SIDE 1
- GOOD/NG สลับ
- UNKNOWN บ่อย
- defect เล็กไม่ถูกจับ

แนวทาง:

- ถ่ายภาพจากกล้องจริง
- train ด้วยสภาพแสงจริง
- เก็บภาพทุก side หลายมุม
- เพิ่มตัวอย่าง NG หลายแบบ

### 20.4 พื้นหลัง

OpenCV ต้องการ contrast ระหว่างวัตถุกับพื้นหลัง

ถ้าพื้นหลังใกล้สีชิ้นงาน:

- จับพื้นหลังแทน
- contour ขาด
- bounding box ใหญ่ผิดปกติ

แนวทาง:

- ใช้พื้นหลังสีตัดกับชิ้นงาน
- ใช้ผิวด้าน ไม่สะท้อน
- ควบคุมแสงให้สม่ำเสมอ

## 21. แนวทางพัฒนาต่อ

แนวทางที่สามารถต่อยอดได้:

- เพิ่ม calibration wizard แบบ step-by-step
- เพิ่มระบบเก็บ calibration profile หลายชุด
- เพิ่ม model version tracking
- เพิ่มหน้า dataset capture สำหรับ train AI
- เพิ่ม confusion matrix ของ side classifier
- เพิ่ม SPC chart เช่น X-bar/R chart
- เพิ่ม export CSV/PDF report
- เพิ่ม role-based access
- เพิ่ม auto backup database
- เพิ่ม health check service แยกจาก Pi
- เพิ่ม Docker deployment

## 22. สรุปสั้น

โปรเจคนี้คือระบบตรวจสอบคุณภาพชิ้นงาน 3D Printing แบบครบวงจร ประกอบด้วย:

- กล้องสำหรับ Live Feed และ capture
- AI สำหรับจำแนก side และตรวจ defect
- YOLO/OpenVINO สำหรับ defect detection
- OpenCV สำหรับวัดขนาด `SIDE 3`
- Supabase สำหรับ database/storage
- Streamlit Dashboard สำหรับ production monitoring
- LINE OA สำหรับ alert และ chatbot
- Integration กับ Bambu Lab A1, TM Cobot และ Raspberry Pi

ระบบถูกออกแบบให้ทำงานกับงานจริง มีการบันทึกข้อมูลย้อนหลัง มีการแจ้งเตือนทันทีเมื่อพบ NG และสามารถดูข้อมูลได้ทั้งผ่าน Dashboard และ LINE OA

