 ขั้นตอนการประมวลผลภาพสำหรับการวัดขนาดชิ้นงานด้วย OpenCV

  ในระบบนี้ OpenCV ถูกนำมาใช้สำหรับการวัดขนาดของชิ้นงานในมุมมอง SIDE 3
  โดยแนวคิดสำคัญคือการแปลงภาพจากกล้องให้อยู่ในรูปแบบที่คอมพิวเตอร์สามารถแยก “ชิ้นงาน” ออกจาก
  “พื้นหลัง” ได้อย่างชัดเจน จากนั้นจึงหาขอบของชิ้นงานและคำนวณระยะต่าง ๆ ในหน่วยพิกเซล
  ก่อนจะแปลงเป็นหน่วยมิลลิเมตรด้วยค่าการสอบเทียบที่กำหนดไว้

  ขั้นตอนแรกของการประมวลผลภาพเริ่มจากการรับภาพสีจากกล้อง ซึ่งเป็นภาพแบบ BGR
  ตามรูปแบบมาตรฐานของ OpenCV อย่างไรก็ตาม
  ภาพสีมีข้อมูลจำนวนมากเกินความจำเป็นสำหรับการวัดขอบวัตถุโดยตรง
  ดังนั้นระบบจึงทำการลดสัญญาณรบกวนด้วย Gaussian Blur ก่อน แล้วจึงแปลงภาพไปยังหลาย color
  space เพื่อใช้ในการแยกวัตถุหลายรูปแบบ ได้แก่ ภาพระดับเทาเพื่อใช้ threshold และภาพ HSV
  เพื่อใช้แยกชิ้นงานที่มีสีเด่นจากพื้นหลังสีขาว

  โค้ดจริงที่ใช้ในส่วนนี้เป็นดังนี้:

  def create_binary_mask(frame):
      blurred = cv2.GaussianBlur(frame, (5, 5), 0)
      hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
      gray = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)

      sat_mask = cv2.inRange(hsv, np.array([0, 40, 40]), np.array([179, 255,
  255]))
      sat_mask = cv2.morphologyEx(sat_mask, cv2.MORPH_OPEN, np.ones((5, 5),
  np.uint8))
      sat_mask = cv2.morphologyEx(sat_mask, cv2.MORPH_CLOSE, np.ones((7, 7),
  np.uint8))

  จากโค้ดข้างต้นจะเห็นได้ว่า ระบบไม่ได้พึ่งการ threshold แบบเดียว แต่เริ่มจากการลองแยกวัตถุด้วยค่า
  saturation ใน HSV ก่อน เนื่องจากในกรณีชิ้นงานมีสีชัดเจน เช่น สีฟ้า
  ระบบจะสามารถแยกชิ้นงานออกจากพื้นหลังสีขาวได้แม่นยำกว่า
  วิธีนี้ช่วยลดปัญหาที่พื้นหลังสว่างเกินไปหรือแสงไม่สม่ำเสมอ

  หลังจากสร้าง sat_mask แล้ว ระบบจะใช้ morphological operations ได้แก่ MORPH_OPEN และ
  MORPH_CLOSE เพื่อกำจัดจุดรบกวนเล็ก ๆ และเชื่อมพื้นที่ของวัตถุให้ต่อเนื่องกันมากขึ้น
  หลักการของขั้นตอนนี้คือ:

  - MORPH_OPEN ใช้ลด noise ขนาดเล็ก
  - MORPH_CLOSE ใช้ปิดรูหรือช่องว่างภายในวัตถุ

  หากวิธีแยกวัตถุจากสีไม่สามารถหา contour ที่เหมาะสมได้ ระบบจะใช้การ threshold แบบ Otsu
  ทั้งภาพปกติและภาพกลับสี เพื่อเลือก mask ที่ให้ contour ของชิ้นงานดีที่สุด ดังโค้ดต่อไปนี้

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

  หลักการของ Otsu Threshold คือการคำนวณค่าตัดแบ่งภาพอัตโนมัติจาก histogram ของภาพ
  โดยไม่ต้องกำหนด threshold ด้วยมือ เหมาะกับงานที่สภาพแสงอาจเปลี่ยนเล็กน้อยในแต่ละครั้ง
  ระบบจะลองทั้งแบบ THRESH_BINARY และ THRESH_BINARY_INV เพราะในบางสภาพแสง
  ชิ้นงานอาจออกมามืดกว่าพื้นหลัง หรือในบางกรณีอาจสว่างกว่าพื้นหลัง

  เมื่อได้ภาพไบนารีแล้ว ขั้นตอนถัดไปคือการหา contour ซึ่งเป็นเส้นขอบของวัตถุในภาพ ระบบจะใช้
  cv2.findContours() เพื่อค้นหา contour ภายนอกทั้งหมด และเลือก contour ที่เหมาะสมที่สุด
  ไม่ใช่เพียง contour ที่ใหญ่ที่สุดเสมอไป แต่ใช้การให้คะแนน contour
  เพื่อหลีกเลี่ยงการเลือกพื้นหลังหรือวัตถุที่ติดขอบภาพ

  def find_best_contour(binary_mask, frame_shape):
      contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL,
  cv2.CHAIN_APPROX_SIMPLE)
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

  ฟังก์ชัน _score_contour() จะคำนึงถึงพื้นที่ของ contour และลดคะแนนกรณี contour
  ไปแตะขอบภาพ เพราะมักเกิดจากพื้นหลังหรือการจับภาพกว้างเกินไป

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

  เมื่อได้ contour ของชิ้นงานแล้ว ระบบจะสร้าง mask ของ contour แบบทึบ
  เพื่อใช้สำหรับการคำนวณจุดวัดภายในชิ้นงานจริง ไม่ใช่เพียงการวัดจาก bounding box ภายนอก

  def build_contour_mask(image_shape, contour):
      mask = np.zeros(image_shape[:2], dtype=np.uint8)
      cv2.drawContours(mask, [contour], -1, 255, thickness=-1)
      return mask

  หลังจากนั้นระบบจะคำนวณแนวแกนหลักของชิ้นงาน โดยใช้ cv2.minAreaRect() เพื่อหา rotated
  rectangle ที่ครอบชิ้นงานให้พอดีที่สุด แล้วนำมาสร้างเวกเตอร์แนวยาวหลัก (axis_unit)
  และแนวตั้งฉาก (perp_unit) เพื่อใช้เป็นแกนอ้างอิงในการวัด

  rect = cv2.minAreaRect(contour)
  center_x, center_y = rect[0]
  rect_w, rect_h = rect[1]
  angle = float(rect[2])
  if rect_w < rect_h:
      angle += 90.0
  angle_rad = np.deg2rad(angle)
  axis_unit = np.array([np.cos(angle_rad), np.sin(angle_rad)], dtype=np.float32)
  perp_unit = np.array([-axis_unit[1], axis_unit[0]], dtype=np.float32)

  หลักการของส่วนนี้คือ ถึงแม้ชิ้นงานจะถูกวางเอียงในภาพ ระบบก็ยังสามารถหา “แกนจริงของชิ้นงาน” ได้
  ไม่ต้องยึดกับแกนแนวนอนหรือแนวตั้งของภาพอย่างเดียว
  ส่งผลให้การวัดมีความสอดคล้องกับรูปทรงของชิ้นงานมากขึ้น

  จากนั้นระบบจะฉายจุดต่าง ๆ ของ contour
  ลงบนแกนหลักของชิ้นงานเพื่อหาจุดเริ่มต้นและจุดสิ้นสุดของแนวยาว แล้วคำนวณความยาวหลัก (LENGTH)
  ของชิ้นงาน ดังนี้

  contour_points = contour.reshape(-1, 2).astype(np.float32)
  relative_points = contour_points - center
  projections = relative_points @ axis_unit
  proj_min = float(np.min(projections))
  proj_max = float(np.max(projections))
  major_axis_px = float(proj_max - proj_min)

  ค่าที่ได้ในขั้นตอนนี้ยังเป็นพิกเซล ซึ่งหมายความว่า OpenCV ยังไม่ได้รู้ขนาดจริงในหน่วยมิลลิเมตร
  แต่เพียงคำนวณระยะบนภาพก่อนเท่านั้น

  สำหรับการวัด TOP และ BOTTOM ระบบไม่ได้ใช้ความกว้างของ bounding box ตรง ๆ
  แต่ใช้การสร้างแถบตัวอย่างตัดขวางแกนหลักของชิ้นงาน แล้วดูว่าที่ตำแหน่งนั้น contour
  เริ่มและจบตรงไหน วิธีนี้ทำให้วัดได้ตามรูปร่างจริงของชิ้นงาน

  top_width = _width_from_mask_projections(
      contour_mask,
      axis_unit,
      perp_unit,
      center,
      top_target_proj,
      band_half_width=sample_band,
  )

  bottom_width = _width_from_mask_projections(
      contour_mask,
      axis_unit,
      perp_unit,
      center,
      bottom_target_proj,
      band_half_width=sample_band,
  )

  หลักการของ _width_from_mask_projections() คือ

  - เลือกเฉพาะ pixel ของชิ้นงานที่อยู่ใกล้ตำแหน่งฉายที่ต้องการ
  - ฉาย pixel เหล่านั้นลงบนแกนตั้งฉากกับชิ้นงาน
  - หา pixel ที่อยู่ซ้ายสุดและขวาสุดในแถบนั้น
  - คำนวณระยะระหว่างสองจุดเป็นความกว้างของชิ้นงานในตำแหน่งนั้น

  ตัวอย่างโค้ดจริง:

  band = np.abs(axis_values - float(target_proj)) <= float(band_half_width)
  band_points = points[band]
  band_perp = perp_values[band]
  min_idx = int(np.argmin(band_perp))
  max_idx = int(np.argmax(band_perp))
  pt_min = band_points[min_idx]
  pt_max = band_points[max_idx]
  width_px = float(np.linalg.norm(pt_max - pt_min))

  เมื่อวัดระยะได้ในหน่วยพิกเซลแล้ว ระบบจึงแปลงเป็นมิลลิเมตรด้วยค่า scale_mm_per_pixel
  ซึ่งได้จากการ calibration ก่อนหน้า

  "length_mm": float(major_axis_px * scale_mm_per_pixel),
  "top_width_mm": float(top_width["width_px"] * scale_mm_per_pixel),
  "bottom_width_mm": float(bottom_width["width_px"] * scale_mm_per_pixel),

  หลักการทางคณิตศาสตร์ของส่วนนี้สามารถอธิบายได้ว่า

  ขนาดจริง (mm) = ระยะที่วัดได้จากภาพ (pixel) × ค่า scale (mm/pixel)

  ตัวอย่างเช่น ถ้าระบบวัดความกว้างได้ 190 พิกเซล และมีค่า scale เท่ากับ 0.1025 mm/pixel
  ขนาดจริงจะเท่ากับ 19.48 mm

  หลังจากคำนวณขนาดเสร็จ ระบบจะนำข้อมูลไปวาดบนภาพ Live Feed
  เพื่อให้ผู้ใช้งานเห็นเส้นอ้างอิงและค่าที่วัดได้แบบทันที โดยเส้นแต่ละชนิดใช้สีแตกต่างกัน เช่น contour
  สีเขียว, แกนหลักสีเหลือง, LENGTH สีแดง, TOP สีน้ำเงิน และ BOTTOM สีม่วง

  โค้ดสำหรับการวาด overlay จริงอยู่ในฟังก์ชัน annotate_side3_measurement() เช่น

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

  และใน PROJECT_APE65_A1/app.py:779 จะเห็นว่าระบบเรียกการวัดจริงใน Live Feed เมื่ออยู่ใน
  SIDE 3 และระบบพร้อมวัด

  live_measurement = measure_side3_from_frame(
      frame,
      measure_settings["scale_mm_per_pixel"],
  )
  live_measurement = smooth_side3_measurement(live_measurement)
  live_measurement = apply_side3_length_offset(live_measurement)
  if has_valid_side3_detection(live_measurement):
      side3_measure = live_measurement

  จากโค้ดนี้จะเห็นว่า หลังวัดแล้วระบบยังมี 3 ขั้นตอนสำคัญเพิ่มเข้ามาอีก ได้แก่

  - smooth_side3_measurement() ใช้ลดการกระพริบของค่า
  - apply_side3_length_offset() ใช้ชดเชยค่าความยาวในกรณีที่ต้องการปรับแก้เชิงระบบ
  - has_valid_side3_detection() ใช้ตรวจว่าผลการวัดน่าเชื่อถือพอหรือไม่ เช่น contour
    ต้องใหญ่พอและไม่ผิดรูปเกินไป

  ดังนั้น หากจะสรุปขั้นตอนการประมวลผลภาพของ OpenCV ในโปรเจคนี้ สามารถเรียงลำดับได้ดังนี้

  1. รับภาพสีจากกล้อง
  2. ลด noise ด้วย Gaussian Blur
  3. แปลงภาพเป็น Grayscale และ HSV
  4. สร้างภาพไบนารีหรือ mask เพื่อแยกชิ้นงานจากพื้นหลัง
  5. ใช้ morphology ลด noise และเชื่อมพื้นที่วัตถุ
  6. หา contour ของชิ้นงาน
  7. เลือก contour ที่เหมาะสมที่สุด
  8. คำนวณแกนหลักของชิ้นงานด้วย rotated rectangle
  9. วัด LENGTH, TOP, BOTTOM ในหน่วย pixel
  10. แปลง pixel เป็น millimeter ด้วยค่า calibration
  11. ตรวจสอบความสมเหตุสมผลของผลลัพธ์
  12. วาดเส้นวัดและค่าแสดงบน Live Feed
  13. ส่งค่าที่วัดได้ไปใช้ตัดสินผ่าน/ไม่ผ่านในระบบ
