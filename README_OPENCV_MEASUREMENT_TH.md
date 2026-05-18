# README - OpenCV Measurement ในโปรเจค PROJECT_APE65_A1

เอกสารนี้อธิบายการใช้งาน OpenCV สำหรับระบบวัดขนาดชิ้นงานในโปรเจค `PROJECT_APE65_A1` โดยอ้างอิงจากโค้ดที่ใช้งานจริงในระบบ เพื่อให้สามารถเข้าใจได้ว่าระบบรับภาพอย่างไร ประมวลผลภาพอย่างไร หา contour อย่างไร คำนวณขนาดอย่างไร และแปลงผลลัพธ์จาก pixel ไปเป็น millimeter ได้อย่างไร

## 1. วัตถุประสงค์ของ OpenCV ในโปรเจคนี้

ในโปรเจคนี้ OpenCV ถูกใช้สำหรับการวัดขนาดของชิ้นงานในมุมมอง `SIDE 3` โดยมีค่าที่ต้องการวัด 3 ค่า คือ

- `TOP`
- `BOTTOM`
- `LENGTH`

ระบบจะรับภาพจากกล้องแล้วใช้เทคนิคประมวลผลภาพเพื่อแยกชิ้นงานออกจากพื้นหลัง จากนั้นจึงหาขอบของชิ้นงานและคำนวณระยะต่าง ๆ ในหน่วยพิกเซล ก่อนแปลงเป็นหน่วยมิลลิเมตรด้วยค่าที่ได้จากการ Calibration

## 2. แนวคิดหลักของการวัด

หลักการสำคัญของระบบวัดนี้คือ

1. รับภาพจากกล้อง
2. ทำให้ภาพสะอาดและเหมาะต่อการวิเคราะห์
3. แยกชิ้นงานออกจากพื้นหลัง
4. หา contour ของชิ้นงาน
5. หาแนวแกนหลักของชิ้นงาน
6. วัดระยะในตำแหน่งที่ต้องการ
7. คำนวณระยะในหน่วย pixel
8. แปลง pixel เป็น millimeter
9. เปรียบเทียบกับค่ามาตรฐานและ tolerance

OpenCV ไม่ได้รู้ขนาดจริงของวัตถุโดยตรง แต่รู้เพียงตำแหน่งของ pixel ในภาพเท่านั้น ดังนั้นระบบจำเป็นต้องมีขั้นตอน Calibration เพื่อหาค่า `scale_mm_per_pixel` ก่อนเสมอ

## 3. โค้ดหลักที่เกี่ยวข้อง

ไฟล์หลักที่ใช้ในระบบวัดมีดังนี้

- [utils/side3_measurement.py](/home/ape01/PROJECT_APE65_A1/utils/side3_measurement.py:1)
- [app.py](/home/ape01/PROJECT_APE65_A1/app.py:756)

`utils/side3_measurement.py` เป็นไฟล์หลักสำหรับ:

- สร้าง binary mask
- หา contour
- คำนวณตำแหน่งการวัด
- วัด `TOP`, `BOTTOM`, `LENGTH`
- วาด overlay
- ทำ calibration preview

ส่วน `app.py` เป็นตัวที่นำผลการวัดไปใช้ใน Live Feed และ workflow จริงของระบบ

## 4. ขั้นตอนการประมวลผลภาพ

### 4.1 รับภาพจากกล้อง

ระบบเริ่มจากการรับภาพจากกล้องในรูปแบบภาพสี ซึ่ง OpenCV จะเก็บในรูปแบบ `BGR`

ภาพที่ได้จากกล้องยังไม่พร้อมสำหรับการวัดทันที เพราะ:

- มี noise
- มีแสงสะท้อน
- มีข้อมูลสีที่มากเกินความจำเป็น
- พื้นหลังอาจมีผลต่อการแยกวัตถุ

ดังนั้นระบบจึงต้องผ่านขั้นตอนประมวลผลภาพก่อน

### 4.2 ลด noise และแปลงภาพ

ในระบบจริง ฟังก์ชัน `create_binary_mask()` เป็นจุดเริ่มต้นของการเตรียมภาพ

โค้ดจริง:

```python
def create_binary_mask(frame):
    blurred = cv2.GaussianBlur(frame, (5, 5), 0)
    hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)
```

คำอธิบาย:

- `GaussianBlur` ใช้ลด noise และทำให้ขอบภาพเรียบขึ้น
- `HSV` ใช้แยกวัตถุจากพื้นหลังด้วยข้อมูลด้านสีและความอิ่มตัวของสี
- `Grayscale` ใช้สำหรับ threshold และการประมวลผลที่ไม่ต้องพึ่งข้อมูลสี

เหตุผลที่ต้องแปลงภาพหลายแบบ:

- หากชิ้นงานมีสีเด่น เช่น สีฟ้า การใช้ HSV จะช่วยแยกวัตถุจากพื้นหลังสีขาวได้ดี
- หากการแยกด้วยสีไม่สำเร็จ ระบบยังสามารถ fallback ไปใช้ threshold จากภาพ grayscale ได้

### 4.3 แยกชิ้นงานจากพื้นหลังด้วย Saturation Mask

ระบบจะพยายามแยกชิ้นงานที่มีสีชัดเจนออกจากพื้นหลังขาวก่อน ด้วยการใช้ค่าสีใน HSV

โค้ดจริง:

```python
sat_mask = cv2.inRange(hsv, np.array([0, 40, 40]), np.array([179, 255, 255]))
sat_mask = cv2.morphologyEx(sat_mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
sat_mask = cv2.morphologyEx(sat_mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
contour = find_best_contour(sat_mask, frame.shape)
if contour is not None and cv2.contourArea(contour) > 3000:
    return gray, sat_mask, contour
```

คำอธิบาย:

- `cv2.inRange()` ใช้สร้าง mask ของ pixel ที่มี saturation สูงพอ
- `MORPH_OPEN` ลบจุด noise เล็ก ๆ
- `MORPH_CLOSE` ปิดรูหรือช่องว่างใน mask
- ถ้า mask นี้ให้ contour ที่ดี ระบบจะใช้ทันที

หลักการ:

- พื้นหลังสีขาวมักมี saturation ต่ำ
- ชิ้นงานที่มีสีเด่นมักมี saturation สูงกว่า
- จึงใช้ความแตกต่างนี้ในการแยกวัตถุจากพื้นหลัง

### 4.4 Threshold แบบ Otsu กรณี fallback

หากการแยกด้วยสีไม่สำเร็จ ระบบจะทดลอง threshold แบบ Otsu ทั้งภาพปกติและภาพกลับสี

โค้ดจริง:

```python
_, binary = cv2.threshold(
    gray,
    0,
    255,
    cv2.THRESH_BINARY + cv2.THRESH_OTSU,
)
_, binary_inv = cv2.threshold(
    gray,
    0,
    255,
    cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
)
```

คำอธิบาย:

- Otsu Threshold เป็นการหาค่าตัดแบ่งอัตโนมัติจาก histogram ของภาพ
- ระบบใช้ทั้ง `THRESH_BINARY` และ `THRESH_BINARY_INV`
- เพราะในบางภาพ ชิ้นงานอาจมืดกว่าพื้นหลัง
- ในบางภาพ ชิ้นงานอาจสว่างกว่าพื้นหลัง

หลังจากนั้นระบบจะเลือก mask ที่ให้ contour ดีที่สุด

## 5. การหา Contour ของชิ้นงาน

เมื่อได้ mask แล้ว ระบบจะใช้ `cv2.findContours()` เพื่อหาเส้นขอบของวัตถุ

โค้ดจริง:

```python
def find_best_contour(binary_mask, frame_shape):
    contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    best = None
    best_score = -1.0
    for contour in contours:
        score = _score_contour(contour, frame_shape)
        if score > best_score:
            best_score = score
            best = contour
    return best
```

ระบบไม่ได้เลือก contour ที่ใหญ่ที่สุดเสมอไป แต่ใช้การให้คะแนน contour เพื่อหลีกเลี่ยงการเลือกพื้นหลังหรือ contour ที่แตะขอบภาพ

โค้ดจริง:

```python
def _score_contour(contour, frame_shape):
    x, y, w, h = cv2.boundingRect(contour)
    frame_h, frame_w = frame_shape[:2]
    area = float(cv2.contourArea(contour))

    touches_border = (
        x <= 2
        or y <= 2
        or (x + w) >= (frame_w - 2)
        or (y + h) >= (frame_h - 2)
    )
    border_penalty = area * 0.65 if touches_border else 0.0
    return area - border_penalty
```

เหตุผล:

- หาก contour แตะขอบภาพ มีโอกาสสูงว่าเป็นพื้นหลังหรือวัตถุที่จับไม่ครบ
- จึงต้องลดคะแนน contour แบบนี้

## 6. การสร้าง Contour Mask

หลังจากได้ contour ของชิ้นงานแล้ว ระบบจะสร้าง mask ใหม่ที่เติมพื้นที่ภายใน contour ให้เต็ม เพื่อใช้เป็นพื้นฐานของการวัดจริง

โค้ดจริง:

```python
def build_contour_mask(image_shape, contour):
    mask = np.zeros(image_shape[:2], dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, thickness=-1)
    return mask
```

การทำเช่นนี้ทำให้ระบบสามารถวิเคราะห์ pixel ภายในพื้นที่ของชิ้นงานได้โดยตรง ไม่ได้อ้างอิงจากเพียงกรอบสี่เหลี่ยมรอบนอก

## 7. การหาแนวแกนหลักของชิ้นงาน

หลังจากได้ contour แล้ว ระบบจะใช้ `cv2.minAreaRect()` เพื่อหากรอบสี่เหลี่ยมหมุนที่ครอบชิ้นงานได้พอดีที่สุด แล้วใช้มุมของกรอบนี้ในการสร้างแนวแกนหลักของชิ้นงาน

โค้ดจริง:

```python
rect = cv2.minAreaRect(contour)
center_x, center_y = rect[0]
rect_w, rect_h = rect[1]
angle = float(rect[2])
if rect_w < rect_h:
    angle += 90.0
angle_rad = np.deg2rad(angle)
axis_unit = np.array([np.cos(angle_rad), np.sin(angle_rad)], dtype=np.float32)
perp_unit = np.array([-axis_unit[1], axis_unit[0]], dtype=np.float32)
```

คำอธิบาย:

- `axis_unit` คือเวกเตอร์แนวยาวหลักของชิ้นงาน
- `perp_unit` คือเวกเตอร์ตั้งฉากกับแนวยาวหลัก

ข้อดีของแนวคิดนี้คือ:

- แม้วางชิ้นงานเอียง ระบบก็ยังวัดตามแนวของชิ้นงานได้
- ไม่ต้องยึดกับแกนแนวนอนหรือแนวตั้งของภาพเท่านั้น

## 8. การหาความยาวของชิ้นงาน (LENGTH)

ระบบจะฉายจุดของ contour ลงบนแกนหลัก (`axis_unit`) เพื่อหา projection ต่ำสุดและสูงสุด จากนั้นหาความต่างของ projection ทั้งสอง

โค้ดจริง:

```python
contour_points = contour.reshape(-1, 2).astype(np.float32)
relative_points = contour_points - center
projections = relative_points @ axis_unit
proj_min = float(np.min(projections))
proj_max = float(np.max(projections))
major_axis_px = float(proj_max - proj_min)
```

หลักการ:

- ถ้า contour เป็นตัวแทนรูปร่างของชิ้นงานจริง
- ค่า `proj_min` และ `proj_max` จะเป็นปลายสองด้านของแนวยาว
- ความต่างของสองค่านี้คือความยาวของชิ้นงานในหน่วย pixel

จากนั้นระบบจะใช้ค่าดังกล่าวเป็น `length_px` และคำนวณเป็นมิลลิเมตร

```python
"length_px": major_axis_px,
"length_mm": float(major_axis_px * scale_mm_per_pixel),
```

## 9. การหาความกว้าง TOP และ BOTTOM

ระบบไม่ได้ใช้ความกว้างของ bounding box ตรง ๆ แต่ใช้วิธีวัดบนแถบที่ตัดผ่านชิ้นงานจริงในตำแหน่งที่กำหนด

### 9.1 การวัดความกว้างจาก mask

โค้ดจริง:

```python
def _width_from_mask_projections(mask, axis_unit, perp_unit, center, target_proj, band_half_width=3.0):
    ys, xs = np.where(mask > 0)
    points = np.column_stack((xs, ys)).astype(np.float32)
    relative = points - center
    axis_values = relative @ axis_unit
    perp_values = relative @ perp_unit

    band = np.abs(axis_values - float(target_proj)) <= float(band_half_width)
    band_points = points[band]
    band_perp = perp_values[band]
    min_idx = int(np.argmin(band_perp))
    max_idx = int(np.argmax(band_perp))
    pt_min = band_points[min_idx]
    pt_max = band_points[max_idx]
    width_px = float(np.linalg.norm(pt_max - pt_min))
```

คำอธิบาย:

- ระบบเลือกเฉพาะ pixel ของชิ้นงานที่อยู่ใกล้ตำแหน่งวัด
- จากนั้นหาจุดซ้ายสุดและขวาสุดในแถบนั้น
- ระยะระหว่างสองจุดคือความกว้างของชิ้นงานในตำแหน่งนั้น

### 9.2 การกำหนด TOP และ BOTTOM

ระบบจะวัดความกว้างใกล้ปลายทั้งสองด้านก่อน เพื่อดูว่าฝั่งไหนแคบกว่า แล้วใช้ฝั่งนั้นเป็น `TOP`

โค้ดจริง:

```python
start_width = _width_from_mask_projections(
    contour_mask,
    axis_unit,
    perp_unit,
    center,
    proj_min + end_offset,
    band_half_width=sample_band,
)
end_width = _width_from_mask_projections(
    contour_mask,
    axis_unit,
    perp_unit,
    center,
    proj_max - end_offset,
    band_half_width=sample_band,
)

start_is_top = start_width["width_px"] <= end_width["width_px"]
top_proj = proj_min if start_is_top else proj_max
bottom_proj = proj_max if start_is_top else proj_min
```

หลังจากนั้นจึงขยับตำแหน่งวัดเข้ามาด้านในอีกระยะหนึ่ง แล้ววัด `TOP` และ `BOTTOM` จริง

```python
top_offset = max(8.0, major_axis_px * 0.25)
top_target_proj = (
    top_proj + top_offset if bottom_proj > top_proj else top_proj - top_offset
)

bottom_offset = max(12.0, major_axis_px * 0.18)
bottom_target_proj = (
    bottom_proj - bottom_offset if bottom_proj > top_proj else bottom_proj + bottom_offset
)
```

ระบบจึงวัดจากตำแหน่งที่สัมพันธ์กับรูปร่างจริงของชิ้นงาน ไม่ใช่ตำแหน่งคงที่บนภาพอย่างเดียว

## 10. การแปลงจาก Pixel เป็น Millimeter

ค่าที่วัดจาก OpenCV เป็นเพียง pixel จึงต้องคูณด้วยค่า scale

โค้ดจริง:

```python
"top_width_mm": float(top_width["width_px"] * scale_mm_per_pixel),
"bottom_width_mm": float(bottom_width["width_px"] * scale_mm_per_pixel),
"length_mm": float(major_axis_px * scale_mm_per_pixel),
```

สมการ:

```text
ขนาดจริง (mm) = ระยะในภาพ (pixel) × scale (mm/pixel)
```

ตัวอย่าง:

- ถ้าวัดได้ 190 pixel
- ค่า scale = 0.1025 mm/pixel

จะได้

```text
190 × 0.1025 = 19.475 mm
```

## 11. การวาดผลบน Live Feed

หลังจากคำนวณเสร็จ ระบบจะวาด contour, เส้นวัด และข้อความกำกับบนภาพ

โค้ดจริง:

```python
if contour is not None:
    cv2.drawContours(annotated, [contour], -1, contour_color, 2)

cv2.line(annotated, pt1, pt2, length_color, 2)

cv2.line(
    annotated,
    (int(round(top_line_start[0])), int(round(top_line_start[1]))),
    (int(round(top_line_end[0])), int(round(top_line_end[1]))),
    top_color,
    3,
)
```

และใช้ `cv2.putText()` แสดงค่า `TOP`, `BOTTOM`, `LENGTH` ที่วัดได้

ระบบกำหนดสีดังนี้:

- contour: สีเขียว
- part axis / rotated box: สีเหลือง
- `LENGTH`: สีแดงเข้ม
- `TOP`: สีน้ำเงิน
- `BOTTOM`: สีม่วง

## 12. การเชื่อมกับระบบ Live Runtime

ใน runtime จริง ส่วนการวัดถูกเรียกจาก `app.py` เมื่อระบบอยู่ใน `SIDE 3`

โค้ดจริง:

```python
live_measurement = measure_side3_from_frame(
    frame,
    measure_settings["scale_mm_per_pixel"],
)
live_measurement = smooth_side3_measurement(live_measurement)
live_measurement = apply_side3_length_offset(live_measurement)
if has_valid_side3_detection(live_measurement):
    side3_measure = live_measurement
```

คำอธิบาย:

- `measure_side3_from_frame()` เป็นฟังก์ชันวัดหลัก
- `smooth_side3_measurement()` ใช้ลดการกระพริบของค่า
- `apply_side3_length_offset()` ใช้ปรับค่า LENGTH ตามค่าชดเชยที่ตั้งไว้
- `has_valid_side3_detection()` ใช้ตรวจว่าผลที่วัดได้มีความน่าเชื่อถือเพียงพอหรือไม่

## 13. สรุปลำดับการทำงานแบบย่อ

ลำดับการประมวลผลภาพจริงของระบบสามารถสรุปได้ดังนี้

1. รับภาพสีจากกล้อง
2. ลด noise ด้วย Gaussian Blur
3. แปลงภาพเป็น HSV และ Grayscale
4. สร้าง mask เพื่อแยกชิ้นงานจากพื้นหลัง
5. ใช้ morphology เพื่อลด noise และเชื่อมพื้นที่วัตถุ
6. หา contour ของชิ้นงาน
7. เลือก contour ที่เหมาะสมที่สุด
8. สร้าง contour mask
9. หาแนวแกนหลักของชิ้นงานด้วย rotated rectangle
10. วัด `LENGTH` ตามแนวแกนหลัก
11. วัด `TOP` และ `BOTTOM` จากแถบตัดขวางที่กำหนด
12. แปลงค่าจาก pixel เป็น millimeter
13. วาดเส้นและแสดงค่าบน Live Feed
14. ส่งค่าที่วัดได้ไปใช้ตัดสินผลในระบบ

## 14. ข้อดีของวิธีนี้

- ใช้ contour ของชิ้นงานจริง ไม่ได้อ้างอิงจากกรอบสี่เหลี่ยมอย่างเดียว
- รองรับการวางชิ้นงานเอียงได้ดีกว่าการวัดตามแกนภาพตรง ๆ
- ปรับใช้กับการแสดงผลบน Live Feed ได้ทันที
- ไม่ต้อง train model สำหรับการวัดมิติ
- เหมาะกับการวัดแบบ realtime ในระบบ inspection

## 15. ข้อจำกัด

- แสงมีผลต่อ threshold และ contour มาก
- พื้นหลังที่ใกล้สีชิ้นงานจะทำให้แยกวัตถุยาก
- แสงสะท้อนบนชิ้นงานโลหะอาจทำให้ contour ผิด
- หากกล้องขยับ ค่า scale จะเปลี่ยนและต้อง calibration ใหม่
- ถ้าชิ้นงานยังไม่นิ่ง ค่าที่วัดได้จะสวิง

## 16. สรุป

OpenCV ในโปรเจคนี้ทำหน้าที่เป็นระบบวัดขนาดชิ้นงานจากภาพ โดยอาศัยการแยกวัตถุออกจากพื้นหลัง หา contour ของชิ้นงาน กำหนดแนวแกนหลัก และวัดระยะในหน่วย pixel ก่อนแปลงเป็นหน่วยมิลลิเมตรด้วยค่า calibration ที่กำหนดไว้ วิธีดังกล่าวช่วยให้ระบบสามารถตรวจสอบมิติของชิ้นงานได้แบบอัตโนมัติและแสดงผลบน Live Feed ได้แบบเวลาจริง เหมาะสำหรับนำไปใช้ในระบบตรวจสอบคุณภาพในสายการผลิต

