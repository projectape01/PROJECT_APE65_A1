# README - การสอบเทียบระบบวัดขนาด (Calibration)

**การสอบเทียบระบบวัดขนาด (Calibration)**

เพื่อให้ระบบวัดขนาดชิ้นงานด้วย OpenCV สามารถแปลงระยะที่ตรวจวัดได้จากภาพในหน่วยพิกเซลให้เป็นหน่วยมิลลิเมตรได้อย่างถูกต้อง จำเป็นต้องมีขั้นตอนการสอบเทียบหรือ Calibration ก่อนนำระบบไปใช้งานจริง หลักการของ Calibration คือการใช้วัตถุมาตรฐานที่ทราบขนาดจริงแน่นอนมาเป็นตัวอ้างอิง จากนั้นให้ระบบวัดวัตถุนั้นในภาพ แล้วนำค่าที่วัดได้มาคำนวณหาอัตราส่วนระหว่างหน่วยพิกเซลกับหน่วยมิลลิเมตร ซึ่งจะถูกนำไปใช้เป็นค่าพื้นฐานในการวัดชิ้นงานจริงในลำดับถัดไป

ในโครงงานนี้ ผู้จัดทำเลือกใช้ Gage Box เป็นวัตถุมาตรฐานสำหรับการสอบเทียบ โดยผู้ใช้งานจะต้องกรอกค่าขนาดจริงของ Gage Box เช่น ความกว้าง ความยาว และความสูง ลงในระบบ จากนั้นวาง Gage Box ไว้ในตำแหน่งเดียวกับที่ใช้วัดชิ้นงานจริง เพื่อให้เงื่อนไขของระยะกล้อง มุมกล้อง และสภาพแสงสอดคล้องกับการใช้งานจริงมากที่สุด

ในระดับโค้ด การตั้งค่าที่เกี่ยวข้องกับระบบวัด SIDE 3 และ Calibration ถูกอ่านจากไฟล์ตั้งค่าผ่านฟังก์ชัน `get_side3_measurement_settings()` ซึ่งอยู่ในไฟล์ `core/project_config.py` โดยระบบจะอ่านค่าหลัก เช่น ค่า `SIDE3_SCALE_MM_PER_PIXEL`, ความสูงของ Gage Box, ความสูงของชิ้นงาน และความสูงของกล้อง ดังโค้ดตัวอย่างต่อไปนี้

```python
def get_side3_measurement_settings():
    cfg = load_local_config()
    raw_scale = _as_float(
        os.getenv("SIDE3_SCALE_MM_PER_PIXEL") or cfg.get("SIDE3_SCALE_MM_PER_PIXEL") or DEFAULT_SIDE3_SCALE_MM_PER_PIXEL,
        DEFAULT_SIDE3_SCALE_MM_PER_PIXEL,
    )
    gagebox_height_mm = _as_float(
        os.getenv("SIDE3_GAGEBOX_HEIGHT_MM") or cfg.get("SIDE3_GAGEBOX_HEIGHT_MM") or 0.0,
        0.0,
    )
    part_height_mm = _as_float(
        os.getenv("SIDE3_PART_HEIGHT_MM") or cfg.get("SIDE3_PART_HEIGHT_MM") or DEFAULT_SIDE3_PART_HEIGHT_MM,
        DEFAULT_SIDE3_PART_HEIGHT_MM,
    )
    camera_height_mm = _as_float(
        os.getenv("SIDE3_CAMERA_HEIGHT_MM") or cfg.get("SIDE3_CAMERA_HEIGHT_MM") or DEFAULT_SIDE3_CAMERA_HEIGHT_MM,
        DEFAULT_SIDE3_CAMERA_HEIGHT_MM,
    )
```

จากโค้ดข้างต้นจะเห็นได้ว่า ระบบมีการเตรียมค่าที่เกี่ยวข้องกับมิติทางกายภาพของการวัดไว้ครบถ้วน โดยเฉพาะค่า `SIDE3_SCALE_MM_PER_PIXEL` ซึ่งเป็นค่าหลักที่ใช้แปลงหน่วยจากพิกเซลไปเป็นมิลลิเมตร

เมื่อผู้ใช้งานกดปุ่ม Calibration ระบบจะเรียก API สำหรับจับภาพอ้างอิงของ SIDE 3 ซึ่งอยู่ในไฟล์ `routes/app_routes.py` ที่ route `/api/side3/calibration/capture` ดังนี้

```python
@app.route("/api/side3/calibration/capture", methods=["POST"])
def api_side3_calibration_capture():
    payload = request.get_json(silent=True) or {}
    frame = runtime.get_raw_frame_snapshot()
    if frame is None:
        return jsonify({"success": False, "message": "No frame available for SIDE 3 calibration."}), 503
```

ในขั้นตอนนี้ ระบบจะดึงภาพปัจจุบันจากกล้อง แล้วนำเข้าสู่กระบวนการตรวจจับ Gage Box โดยเรียกฟังก์ชัน `measure_calibration_box_from_frame()` ซึ่งเป็นฟังก์ชันหลักของการวัดวัตถุอ้างอิง ดังตัวอย่างต่อไปนี้

```python
calibration_measurement = runtime.measure_calibration_box_from_frame(
    frame,
    runtime.get_side3_measurement_settings()["scale_mm_per_pixel"],
    known_height_mm,
)
```

ฟังก์ชัน `measure_calibration_box_from_frame()` อยู่ในไฟล์ `utils/side3_measurement.py` และมีหน้าที่สำคัญคือการหา contour ของ Gage Box จากภาพ แล้ววัดความยาวและความกว้างของ Gage Box ในหน่วยพิกเซล โดยเริ่มต้นจากการหา contour ของวัตถุมาตรฐานก่อน ดังโค้ดต่อไปนี้

```python
def measure_calibration_box_from_frame(frame, scale_mm_per_pixel, known_height_mm=None):
    contour = find_calibration_box_contour(frame)
    contour_area = float(cv2.contourArea(contour))
    frame_h, frame_w = frame.shape[:2]
    bbox = cv2.boundingRect(contour)
    x, y, w, h = bbox
```

หลังจากได้ contour แล้ว ระบบจะคำนวณกรอบหมุน (`minAreaRect`) เพื่อหาแนวอ้างอิงของ Gage Box และสร้างแกนหลักของวัตถุ

```python
rect = cv2.minAreaRect(contour)
ordered_box = _order_box_points(cv2.boxPoints(rect))
center_x, center_y = rect[0]
rect_w, rect_h = rect[1]
angle = float(rect[2])
if rect_w < rect_h:
    angle += 90.0
angle_rad = np.deg2rad(angle)
axis_unit = np.array([np.cos(angle_rad), np.sin(angle_rad)], dtype=np.float32)
center = np.array([center_x, center_y], dtype=np.float32)
perp_unit = np.array([-axis_unit[1], axis_unit[0]], dtype=np.float32)
```

อย่างไรก็ตาม สำหรับการ Calibration ในโปรเจคนี้ ผู้จัดทำไม่ได้ใช้การวัดตามแกนหมุนทั้งหมดโดยตรง แต่มีการล็อกเส้นวัดให้ยึดกับขอบบนและขอบด้านขวาของ Gage Box ในภาพ เพื่อให้การวัดมีความตรงไปตรงมาและเข้าใจง่ายขึ้นสำหรับการสอบเทียบ โดยมีโค้ดดังนี้

```python
chosen_length = _horizontal_edge_line_from_mask(
    contour_mask,
    target_y=float(y) + inward_offset_px,
    band_half_width=length_band,
)
chosen_width = _vertical_edge_line_from_mask(
    contour_mask,
    target_x=float(x + w - 1) - inward_offset_px,
    band_half_width=width_band,
)
```

จากนั้นระบบจะได้ค่าความยาวและความกว้างในหน่วยพิกเซลของ Gage Box

```python
length_px = float(chosen_length["length_px"])
width_px = float(chosen_width["length_px"])
```

เมื่อผู้ใช้งานกรอกค่าจริงของ Gage Box เช่น `width_mm` และ `length_mm` ระบบจะนำค่าขนาดจริงมาหารด้วยค่าที่วัดได้ในภาพเพื่อคำนวณ scale ในแต่ละมิติ ดังโค้ดจริงใน route Calibration ต่อไปนี้

```python
if payload_key == "width_mm":
    width_px = float(calibration_measurement.get("width_px") or 0.0)
    if width_px > 0:
        scale_candidates.append(parsed / width_px)
elif payload_key == "length_mm":
    length_px = float(calibration_measurement.get("length_px") or 0.0)
    if length_px > 0:
        scale_candidates.append(parsed / length_px)
```

สมการทางคณิตศาสตร์ที่ใช้มีลักษณะดังนี้

```text
Scale (mm/pixel) = ขนาดจริงของวัตถุ (mm) / ขนาดที่วัดได้ในภาพ (pixel)
```

ตัวอย่างเช่น หาก Gage Box มีความยาวจริง 75 มิลลิเมตร และระบบวัดความยาวจากภาพได้ 730 พิกเซล ค่า scale ในแนวยาวจะเท่ากับ

```text
75 / 730 = 0.10274 mm/pixel
```

หากมีการกรอกทั้งค่าความกว้างและความยาว ระบบจะเก็บ scale จากทั้งสองมิติไว้ในรายการ `scale_candidates` แล้วเฉลี่ยออกมาเป็นค่า scale สุดท้าย

```python
applied_scale = None
if scale_candidates:
    applied_scale = sum(scale_candidates) / len(scale_candidates)
    cfg["SIDE3_SCALE_MM_PER_PIXEL"] = applied_scale
```

เมื่อได้ค่า `applied_scale` แล้ว ระบบจะบันทึกค่านี้ลงในไฟล์ตั้งค่าของโปรเจค (`config.json`) เพื่อใช้ในการวัดชิ้นงานจริงในขั้นตอนถัดไป นอกจากนี้ยังมีการบันทึกภาพอ้างอิงของการ Calibration ไว้ในโฟลเดอร์ `calibration` ด้วย เพื่อใช้ตรวจสอบย้อนหลัง

```python
cfg["SIDE3_REFERENCE_IMAGE"] = local_path
cfg["SIDE3_REFERENCE_CAPTURED_AT"] = captured_at_dt.isoformat()
runtime.save_local_config(cfg)
```

ในส่วนของการแสดงผล ผู้ใช้งานสามารถกด Preview เพื่อตรวจสอบได้ก่อนว่าระบบจับ contour และเส้นวัดของ Gage Box ถูกต้องหรือไม่ โดยฟังก์ชันที่ใช้วาดผล Preview คือ `annotate_calibration_box_measurement()` ซึ่งจะวาด contour ของวัตถุและเส้นวัดความยาวและความกว้างลงบนภาพจริง ดังโค้ดต่อไปนี้

```python
def annotate_calibration_box_measurement(frame, measurement):
    annotated = frame.copy()
    contour = measurement.get("contour")
    if contour is not None:
        cv2.drawContours(annotated, [contour], -1, (34, 197, 94), 2)
```

และฟังก์ชันวาดเส้นวัดจริงมีลักษณะดังนี้

```python
_draw_line(
    measurement.get("length_line_start"),
    measurement.get("length_line_end"),
    (59, 130, 246),
    f"L {float(measurement.get('length_mm') or 0.0):.2f} mm",
)
_draw_line(
    measurement.get("width_line_start"),
    measurement.get("width_line_end"),
    (168, 85, 247),
    f"W {float(measurement.get('width_mm') or 0.0):.2f} mm",
)
```

นอกจากนั้น ระบบยังมีการตรวจสอบความเหมาะสมของ contour ที่ใช้ใน Calibration โดยไม่เลือกวัตถุที่เล็กเกินไป ใหญ่เกินไป หรือแตะขอบภาพ เพื่อป้องกันความผิดพลาดจากการตรวจจับพื้นหลังหรือวัตถุอื่น ตัวอย่างของเกณฑ์การประเมิน contour อยู่ในฟังก์ชัน `_calibration_contour_score()` เช่น

```python
if w < 40 or h < 40:
    return -1.0
if w >= int(frame_w * 0.9) or h >= int(frame_h * 0.9):
    return -1.0

if fill_ratio < 0.45:
    return -1.0

if area_ratio < 0.01:
    return -1.0
if area_ratio > 0.28:
    return -1.0
```

จากเงื่อนไขเหล่านี้จะเห็นได้ว่า ระบบพยายามเลือก contour ที่มีขนาดสมเหตุสมผล อยู่ใกล้กึ่งกลางภาพ และมีลักษณะเป็นวัตถุเต็มชิ้นจริง เพื่อเพิ่มความน่าเชื่อถือของผลการสอบเทียบ

อย่างไรก็ตาม แม้ว่าระบบจะรองรับการป้อนค่าความสูงของ Gage Box (`height_mm`) ด้วย แต่ในโค้ดปัจจุบัน ค่านี้ยังไม่ได้ถูกใช้เป็นตัวหลักในการคำนวณ scale โดยตรงเหมือนกับ `width_mm` และ `length_mm` ค่าความสูงถูกใช้ในลักษณะข้อมูลประกอบบางส่วน เช่น การคำนวณระยะชดเชยของเส้นวัดในภาพ ดังนั้นการสอบเทียบหลักของระบบในปัจจุบันจึงยังอาศัยมิติด้านความกว้างและความยาวเป็นสำคัญ

สรุปได้ว่า ขั้นตอน Calibration ในโครงงานนี้เป็นกระบวนการสำคัญที่ทำให้ระบบสามารถแปลงค่าการวัดจากหน่วยพิกเซลให้เป็นหน่วยมิลลิเมตรได้อย่างถูกต้อง โดยใช้ Gage Box เป็นวัตถุมาตรฐาน อาศัย OpenCV ในการตรวจหาขอบเขตของวัตถุและวัดขนาดในภาพ จากนั้นคำนวณค่า `scale_mm_per_pixel` จากอัตราส่วนระหว่างขนาดจริงกับขนาดที่วัดได้ในภาพ แล้วบันทึกค่าไว้เพื่อใช้วัดชิ้นงานจริงใน `SIDE 3` ต่อไป การทำ Calibration อย่างถูกต้องจึงมีผลโดยตรงต่อความแม่นยำของระบบวัดขนาดทั้งหมด

