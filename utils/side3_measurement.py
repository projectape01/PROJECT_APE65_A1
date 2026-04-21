import cv2
import numpy as np


def find_largest_contour(binary_mask):
    contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


def _score_contour(contour, frame_shape):
    x, y, w, h = cv2.boundingRect(contour)
    frame_h, frame_w = frame_shape[:2]
    area = float(cv2.contourArea(contour))
    if area <= 0:
        return -1.0

    touches_border = (
        x <= 2
        or y <= 2
        or (x + w) >= (frame_w - 2)
        or (y + h) >= (frame_h - 2)
    )
    border_penalty = area * 0.65 if touches_border else 0.0
    return area - border_penalty


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


def create_binary_mask(frame):
    blurred = cv2.GaussianBlur(frame, (5, 5), 0)
    hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)

    # Prefer colored foreground over white background.
    sat_mask = cv2.inRange(hsv, np.array([0, 40, 40]), np.array([179, 255, 255]))
    sat_mask = cv2.morphologyEx(sat_mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    sat_mask = cv2.morphologyEx(sat_mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    contour = find_best_contour(sat_mask, frame.shape)
    if contour is not None and cv2.contourArea(contour) > 3000:
        return gray, sat_mask, contour

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

    best_mask = None
    best_contour = None
    best_area = -1.0

    for mask in (binary, binary_inv):
        contour = find_best_contour(mask, frame.shape)
        if contour is None:
            continue
        area = float(cv2.contourArea(contour))
        if area > best_area:
            best_area = area
            best_mask = mask
            best_contour = contour

    if best_mask is None or best_contour is None:
        raise ValueError("No contour found after thresholding.")

    return blurred, best_mask, best_contour


def build_contour_mask(image_shape, contour):
    mask = np.zeros(image_shape[:2], dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, thickness=-1)
    return mask


def _distance_between_points(pt_a, pt_b):
    return float(np.linalg.norm(np.array(pt_a, dtype=np.float32) - np.array(pt_b, dtype=np.float32)))


def _order_box_points(points):
    pts = np.array(points, dtype=np.float32)
    sorted_idx = np.argsort(pts[:, 1])
    top_two = pts[sorted_idx[:2]]
    bottom_two = pts[sorted_idx[2:]]
    top_left, top_right = top_two[np.argsort(top_two[:, 0])]
    bottom_left, bottom_right = bottom_two[np.argsort(bottom_two[:, 0])]
    return np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.float32)


def _width_from_mask_projections(mask, axis_unit, perp_unit, center, target_proj, band_half_width=3.0):
    ys, xs = np.where(mask > 0)
    if xs.size == 0:
        raise ValueError("No contour pixels available for width measurement.")

    points = np.column_stack((xs, ys)).astype(np.float32)
    relative = points - center
    axis_values = relative @ axis_unit
    perp_values = relative @ perp_unit

    band = np.abs(axis_values - float(target_proj)) <= float(band_half_width)
    if not np.any(band):
        raise ValueError("No contour pixels found near target projection.")

    band_points = points[band]
    band_perp = perp_values[band]
    min_idx = int(np.argmin(band_perp))
    max_idx = int(np.argmax(band_perp))
    pt_min = band_points[min_idx]
    pt_max = band_points[max_idx]
    width_px = float(np.linalg.norm(pt_max - pt_min))

    return {
        "width_px": width_px,
        "pt_min": [float(pt_min[0]), float(pt_min[1])],
        "pt_max": [float(pt_max[0]), float(pt_max[1])],
    }


def _length_line_on_part(mask, axis_unit, perp_unit, center, proj_min, proj_max, band_half_width=3.0):
    ys, xs = np.where(mask > 0)
    if xs.size == 0:
        raise ValueError("No contour pixels available for length measurement.")

    points = np.column_stack((xs, ys)).astype(np.float32)
    relative = points - center
    axis_values = relative @ axis_unit
    perp_values = relative @ perp_unit

    perp_min = float(np.min(perp_values))
    perp_max = float(np.max(perp_values))
    if perp_max - perp_min < 1.0:
        perp_candidates = [0.0]
    else:
        perp_candidates = np.linspace(perp_min * 0.65, perp_max * 0.65, 7).tolist()

    best = None
    best_score = -1.0
    for target_perp in perp_candidates:
        band = np.abs(perp_values - float(target_perp)) <= float(band_half_width)
        if not np.any(band):
            continue

        band_axis = axis_values[band]
        length_px = float(np.max(band_axis) - np.min(band_axis))
        coverage_ratio = length_px / max(1.0, float(proj_max - proj_min))
        score = length_px * (0.8 + min(coverage_ratio, 1.0))
        if score <= best_score:
            continue

        start = center + (axis_unit * float(np.min(band_axis))) + (perp_unit * float(target_perp))
        end = center + (axis_unit * float(np.max(band_axis))) + (perp_unit * float(target_perp))
        best = {
            "line_start": [float(start[0]), float(start[1])],
            "line_end": [float(end[0]), float(end[1])],
            "perp_offset": float(target_perp),
            "length_px": length_px,
        }
        best_score = score

    if best is None:
        start = center + (axis_unit * float(proj_min))
        end = center + (axis_unit * float(proj_max))
        best = {
            "line_start": [float(start[0]), float(start[1])],
            "line_end": [float(end[0]), float(end[1])],
            "perp_offset": 0.0,
            "length_px": float(proj_max - proj_min),
        }
    return best


def _line_support_score(contour_points, start_pt, end_pt, distance_threshold=4.0):
    start = np.array(start_pt, dtype=np.float32)
    end = np.array(end_pt, dtype=np.float32)
    segment = end - start
    seg_len = float(np.linalg.norm(segment))
    if seg_len <= 1e-6:
        return 0.0

    direction = segment / seg_len
    rel = contour_points - start
    proj = rel @ direction
    valid = (proj >= -2.0) & (proj <= (seg_len + 2.0))
    if not np.any(valid):
        return 0.0

    closest = start + np.outer(proj[valid], direction)
    distances = np.linalg.norm(contour_points[valid] - closest, axis=1)
    inlier_count = float(np.sum(distances <= float(distance_threshold)))
    return inlier_count / max(seg_len, 1.0)


def _edge_line_from_mask(mask, axis_unit, perp_unit, center, target_value, band_half_width=3.0, parallel_to="axis"):
    ys, xs = np.where(mask > 0)
    if xs.size == 0:
        raise ValueError("No contour pixels available for calibration edge measurement.")

    points = np.column_stack((xs, ys)).astype(np.float32)
    relative = points - center
    axis_values = relative @ axis_unit
    perp_values = relative @ perp_unit

    if parallel_to == "axis":
        band = np.abs(perp_values - float(target_value)) <= float(band_half_width)
        if not np.any(band):
            raise ValueError("No contour pixels found for calibration length edge.")
        band_points = points[band]
        band_axis = axis_values[band]
        start = band_points[int(np.argmin(band_axis))]
        end = band_points[int(np.argmax(band_axis))]
    else:
        band = np.abs(axis_values - float(target_value)) <= float(band_half_width)
        if not np.any(band):
            raise ValueError("No contour pixels found for calibration width edge.")
        band_points = points[band]
        band_perp = perp_values[band]
        start = band_points[int(np.argmin(band_perp))]
        end = band_points[int(np.argmax(band_perp))]

    return {
        "start": [float(start[0]), float(start[1])],
        "end": [float(end[0]), float(end[1])],
        "length_px": float(np.linalg.norm(end - start)),
        "mid_x": float((start[0] + end[0]) / 2.0),
        "mid_y": float((start[1] + end[1]) / 2.0),
    }


def _horizontal_edge_line_from_mask(mask, target_y, band_half_width=3.0):
    ys, xs = np.where(mask > 0)
    if xs.size == 0:
        raise ValueError("No contour pixels available for horizontal edge measurement.")
    band = np.abs(ys.astype(np.float32) - float(target_y)) <= float(band_half_width)
    if not np.any(band):
        raise ValueError("No contour pixels found for top edge.")
    band_xs = xs[band]
    band_ys = ys[band]
    left_idx = int(np.argmin(band_xs))
    right_idx = int(np.argmax(band_xs))
    fixed_y = float(np.median(band_ys.astype(np.float32)))
    start = np.array([band_xs[left_idx], fixed_y], dtype=np.float32)
    end = np.array([band_xs[right_idx], fixed_y], dtype=np.float32)
    return {
        "start": [float(start[0]), float(start[1])],
        "end": [float(end[0]), float(end[1])],
        "length_px": float(np.linalg.norm(end - start)),
        "mid_x": float((start[0] + end[0]) / 2.0),
        "mid_y": float((start[1] + end[1]) / 2.0),
    }


def _vertical_edge_line_from_mask(mask, target_x, band_half_width=3.0):
    ys, xs = np.where(mask > 0)
    if xs.size == 0:
        raise ValueError("No contour pixels available for vertical edge measurement.")
    band = np.abs(xs.astype(np.float32) - float(target_x)) <= float(band_half_width)
    if not np.any(band):
        raise ValueError("No contour pixels found for side edge.")
    band_xs = xs[band]
    band_ys = ys[band]
    top_idx = int(np.argmin(band_ys))
    bottom_idx = int(np.argmax(band_ys))
    fixed_x = float(np.median(band_xs.astype(np.float32)))
    start = np.array([fixed_x, band_ys[top_idx]], dtype=np.float32)
    end = np.array([fixed_x, band_ys[bottom_idx]], dtype=np.float32)
    return {
        "start": [float(start[0]), float(start[1])],
        "end": [float(end[0]), float(end[1])],
        "length_px": float(np.linalg.norm(end - start)),
        "mid_x": float((start[0] + end[0]) / 2.0),
        "mid_y": float((start[1] + end[1]) / 2.0),
    }


def measure_calibration_box_from_frame(frame, scale_mm_per_pixel, known_height_mm=None):
    contour = find_calibration_box_contour(frame)
    contour_area = float(cv2.contourArea(contour))
    frame_h, frame_w = frame.shape[:2]
    bbox = cv2.boundingRect(contour)
    x, y, w, h = bbox

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

    contour_mask = build_contour_mask(frame.shape, contour)
    contour_points = contour.reshape(-1, 2).astype(np.float32)
    relative = contour_points - center
    axis_values = relative @ axis_unit
    perp_values = relative @ perp_unit
    proj_min = float(np.min(axis_values))
    proj_max = float(np.max(axis_values))
    perp_min = float(np.min(perp_values))
    perp_max = float(np.max(perp_values))

    length_band = max(3.0, min(rect_h, rect_w) * 0.08)
    width_band = max(3.0, max(rect_h, rect_w) * 0.08)

    inward_offset_px = 0.0
    try:
        if known_height_mm is not None and float(known_height_mm) > 0 and float(scale_mm_per_pixel) > 0:
            projected_height_px = float(known_height_mm) / float(scale_mm_per_pixel)
            inward_offset_px = min(12.0, max(0.0, projected_height_px * 0.06))
    except Exception:
        inward_offset_px = 0.0

    # For calibration, lock to the visible top edge and right side edge in image space.
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
    length_start = chosen_length["start"]
    length_end = chosen_length["end"]
    width_start = chosen_width["start"]
    width_end = chosen_width["end"]
    length_px = float(chosen_length["length_px"])
    width_px = float(chosen_width["length_px"])

    return {
        "contour": contour,
        "contour_area": contour_area,
        "frame_w": int(frame_w),
        "frame_h": int(frame_h),
        "bbox": (int(x), int(y), int(w), int(h)),
        "rotated_box": ordered_box.astype(np.int32).tolist(),
        "length_line_start": [float(length_start[0]), float(length_start[1])],
        "length_line_end": [float(length_end[0]), float(length_end[1])],
        "width_line_start": [float(width_start[0]), float(width_start[1])],
        "width_line_end": [float(width_end[0]), float(width_end[1])],
        "length_px": float(length_px),
        "width_px": float(width_px),
        "length_mm": float(length_px * scale_mm_per_pixel),
        "width_mm": float(width_px * scale_mm_per_pixel),
        "scale_mm_per_pixel": float(scale_mm_per_pixel),
        "known_height_mm": float(known_height_mm) if known_height_mm is not None else None,
        "inward_offset_px": float(inward_offset_px),
    }


def _calibration_contour_score(contour, frame_shape):
    frame_h, frame_w = frame_shape[:2]
    area = float(cv2.contourArea(contour))
    if area <= 0.0:
        return -1.0

    rect = cv2.minAreaRect(contour)
    rect_w, rect_h = rect[1]
    rect_area = float(rect_w * rect_h)
    if rect_area <= 0.0:
        return -1.0

    x, y, w, h = cv2.boundingRect(contour)
    if w < 40 or h < 40:
        return -1.0
    if w >= int(frame_w * 0.9) or h >= int(frame_h * 0.9):
        return -1.0

    aspect_ratio = max(rect_w, rect_h) / max(1.0, min(rect_w, rect_h))
    fill_ratio = area / rect_area
    if fill_ratio < 0.45:
        return -1.0

    area_ratio = rect_area / float(frame_w * frame_h)
    if area_ratio < 0.01:
        return -1.0
    if area_ratio > 0.28:
        return -1.0

    touches_border = (x <= 4 or y <= 4 or (x + w) >= (frame_w - 4) or (y + h) >= (frame_h - 4))
    if touches_border:
        return -1.0

    center_x = x + (w / 2.0)
    center_y = y + (h / 2.0)
    center_dx = abs(center_x - (frame_w / 2.0)) / max(1.0, frame_w / 2.0)
    center_dy = abs(center_y - (frame_h / 2.0)) / max(1.0, frame_h / 2.0)
    center_penalty = max(0.55, 1.0 - (0.45 * center_dx) - (0.30 * center_dy))
    aspect_bonus = 1.15 if 1.4 <= aspect_ratio <= 3.2 else 1.0

    return rect_area * (fill_ratio ** 2) * aspect_bonus * center_penalty


def _find_best_calibration_contour_from_mask(mask, frame_shape):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best_contour = None
    best_score = -1.0
    frame_h, frame_w = frame_shape[:2]
    candidate_hulls = []
    for contour in contours:
        hull = cv2.convexHull(contour)
        score = _calibration_contour_score(hull, frame_shape)
        if score > 0:
            x, y, w, h = cv2.boundingRect(hull)
            center_x = x + (w / 2.0)
            center_dx = abs(center_x - (frame_w / 2.0)) / max(1.0, frame_w / 2.0)
            area_ratio = float(cv2.contourArea(hull)) / max(1.0, float(frame_w * frame_h))
            if center_dx <= 0.28 and area_ratio >= 0.002:
                candidate_hulls.append(hull)
        if score > best_score:
            best_score = score
            best_contour = hull

    if len(candidate_hulls) >= 2:
        merged = np.vstack(candidate_hulls)
        merged_hull = cv2.convexHull(merged)
        merged_score = _calibration_contour_score(merged_hull, frame_shape)
        if merged_score > best_score:
            best_score = merged_score
            best_contour = merged_hull
    return best_contour, best_score


def find_calibration_box_contour(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Metallic gage blocks often split into bright/dark regions, so evaluate multiple masks
    # and prefer the contour whose min-area rectangle is most filled like a full box.
    edges = cv2.Canny(blurred, 35, 110)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    edge_mask = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))

    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, binary_inv = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        41,
        6,
    )

    candidate_masks = []
    for raw_mask in (edge_mask, binary, binary_inv, adaptive):
        mask = cv2.morphologyEx(raw_mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        candidate_masks.append(mask)

    best_contour = None
    best_score = -1.0
    for mask in candidate_masks:
        contour, score = _find_best_calibration_contour_from_mask(mask, frame.shape)
        if contour is not None and score > best_score:
            best_score = score
            best_contour = contour

    if best_contour is None:
        _, _binary_mask, best_contour = create_binary_mask(frame)

    if best_contour is None:
        raise ValueError("No calibration box contour found.")
    return best_contour


def annotate_calibration_box_measurement(frame, measurement):
    annotated = frame.copy()
    contour = measurement.get("contour")
    if contour is not None:
        cv2.drawContours(annotated, [contour], -1, (34, 197, 94), 2)

    def _draw_line(line_start, line_end, color, text):
        if not line_start or not line_end:
            return
        pt1 = (int(round(line_start[0])), int(round(line_start[1])))
        pt2 = (int(round(line_end[0])), int(round(line_end[1])))
        cv2.line(annotated, pt1, pt2, color, 3)
        label_x = max(12, min(annotated.shape[1] - 180, pt2[0] + 10))
        label_y = max(24, min(annotated.shape[0] - 12, pt2[1] - 8))
        cv2.putText(
            annotated,
            text,
            (label_x, label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            color,
            2,
            cv2.LINE_AA,
        )

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

    cv2.putText(
        annotated,
        "CALIBRATION PREVIEW",
        (18, 32),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        (250, 204, 21),
        2,
        cv2.LINE_AA,
    )
    return annotated


def measure_side3_from_frame(frame, scale_mm_per_pixel):
    _, binary_mask, contour = create_binary_mask(frame)
    contour_mask = build_contour_mask(frame.shape, contour)
    bbox = cv2.boundingRect(contour)
    x, y, w, h = bbox
    contour_area = float(cv2.contourArea(contour))
    frame_h, frame_w = frame.shape[:2]
    rect = cv2.minAreaRect(contour)
    ordered_box = _order_box_points(cv2.boxPoints(rect))
    box_points = ordered_box.astype(np.int32)
    center_x, center_y = rect[0]
    rect_w, rect_h = rect[1]
    angle = float(rect[2])
    if rect_w < rect_h:
        angle += 90.0
    angle_rad = np.deg2rad(angle)
    axis_unit = np.array([np.cos(angle_rad), np.sin(angle_rad)], dtype=np.float32)
    center = np.array([center_x, center_y], dtype=np.float32)
    perp_unit = np.array([-axis_unit[1], axis_unit[0]], dtype=np.float32)

    contour_points = contour.reshape(-1, 2).astype(np.float32)
    relative_points = contour_points - center
    projections = relative_points @ axis_unit
    proj_min = float(np.min(projections))
    proj_max = float(np.max(projections))
    major_axis_px = float(proj_max - proj_min)
    axis_start = center + (axis_unit * proj_min)
    axis_end = center + (axis_unit * proj_max)

    end_offset = max(8.0, major_axis_px * 0.14)
    sample_band = max(2.5, major_axis_px * 0.012)
    length_line = _length_line_on_part(
        contour_mask,
        axis_unit,
        perp_unit,
        center,
        proj_min,
        proj_max,
        band_half_width=sample_band,
    )
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

    top_offset = max(8.0, major_axis_px * 0.25)
    top_target_proj = (
        top_proj + top_offset if bottom_proj > top_proj else top_proj - top_offset
    )
    top_width = _width_from_mask_projections(
        contour_mask,
        axis_unit,
        perp_unit,
        center,
        top_target_proj,
        band_half_width=sample_band,
    )

    bottom_offset = max(12.0, major_axis_px * 0.18)
    bottom_target_proj = (
        bottom_proj - bottom_offset if bottom_proj > top_proj else bottom_proj + bottom_offset
    )
    bottom_width = _width_from_mask_projections(
        contour_mask,
        axis_unit,
        perp_unit,
        center,
        bottom_target_proj,
        band_half_width=sample_band,
    )

    return {
        "contour": contour,
        "bbox": (x, y, w, h),
        "bbox_x": int(x),
        "bbox_y": int(y),
        "bbox_w": int(w),
        "bbox_h": int(h),
        "bbox_area": int(w * h),
        "contour_area": contour_area,
        "frame_w": int(frame_w),
        "frame_h": int(frame_h),
        "rotated_box": box_points.tolist(),
        "center_x": float(center_x),
        "center_y": float(center_y),
        "angle_deg": angle,
        "axis_start": [float(axis_start[0]), float(axis_start[1])],
        "axis_end": [float(axis_end[0]), float(axis_end[1])],
        "length_line_start": length_line["line_start"],
        "length_line_end": length_line["line_end"],
        "major_axis_px": major_axis_px,
        "length_px": major_axis_px,
        "length_mm": float(major_axis_px * scale_mm_per_pixel),
        "top_side": "start" if start_is_top else "end",
        "top_width_px": float(top_width["width_px"]),
        "top_width_mm": float(top_width["width_px"] * scale_mm_per_pixel),
        "top_line_start": top_width["pt_min"],
        "top_line_end": top_width["pt_max"],
        "bottom_width_px": float(bottom_width["width_px"]),
        "bottom_width_mm": float(bottom_width["width_px"] * scale_mm_per_pixel),
        "bottom_line_start": bottom_width["pt_min"],
        "bottom_line_end": bottom_width["pt_max"],
        "scale_mm_per_pixel": float(scale_mm_per_pixel),
    }


def annotate_side3_measurement(frame, measurement, saved_label=None):
    annotated = frame.copy()
    contour = measurement.get("contour")
    bbox = measurement.get("bbox") or (0, 0, 0, 0)
    x, y, w, h = bbox
    contour_color = (0, 255, 0)
    box_color = (0, 200, 255)
    length_color = (0, 0, 180)
    top_color = (255, 0, 0)
    bottom_color = (180, 0, 180)

    def _clamp_text_origin(px, py):
        px = int(round(px))
        py = int(round(py))
        px = max(12, min(annotated.shape[1] - 220, px))
        py = max(24, min(annotated.shape[0] - 12, py))
        return (px, py)

    def _line_end_label_pos(line_start, line_end, pad=14.0):
        if not line_start or not line_end:
            return None

        start = np.array(line_start, dtype=np.float32)
        end = np.array(line_end, dtype=np.float32)

        anchor = end if end[0] >= start[0] else start
        other = start if anchor is end else end
        direction = anchor - other
        length = float(np.linalg.norm(direction))
        if length <= 1e-6:
            return _clamp_text_origin(anchor[0] + pad, anchor[1])

        unit = direction / length
        label_point = anchor + (unit * float(pad))
        return _clamp_text_origin(label_point[0], label_point[1])

    if contour is not None:
        cv2.drawContours(annotated, [contour], -1, contour_color, 2)

    rotated_box = measurement.get("rotated_box") or []
    if rotated_box:
        cv2.polylines(
            annotated,
            [np.array(rotated_box, dtype=np.int32)],
            True,
            box_color,
            3,
        )

    center_x = float(measurement.get("center_x") or (x + (w / 2.0)))
    center_y = float(measurement.get("center_y") or (y + (h / 2.0)))
    length_line_start = measurement.get("length_line_start")
    length_line_end = measurement.get("length_line_end")
    axis_start = measurement.get("axis_start")
    axis_end = measurement.get("axis_end")
    if length_line_start and length_line_end:
        pt1 = (int(round(length_line_start[0])), int(round(length_line_start[1])))
        pt2 = (int(round(length_line_end[0])), int(round(length_line_end[1])))
    elif axis_start and axis_end:
        pt1 = (int(round(axis_start[0])), int(round(axis_start[1])))
        pt2 = (int(round(axis_end[0])), int(round(axis_end[1])))
    else:
        angle_deg = float(measurement.get("angle_deg") or 0.0)
        major_axis_px = float(measurement.get("major_axis_px") or max(w, h))
        half_axis = max(20, int(round(major_axis_px * 0.5)))
        angle_rad = np.deg2rad(angle_deg)
        dx = int(round(np.cos(angle_rad) * half_axis))
        dy = int(round(np.sin(angle_rad) * half_axis))
        pt1 = (int(round(center_x - dx)), int(round(center_y - dy)))
        pt2 = (int(round(center_x + dx)), int(round(center_y + dy)))
    cv2.line(annotated, pt1, pt2, length_color, 2)

    top_line_start = measurement.get("top_line_start")
    top_line_end = measurement.get("top_line_end")
    if top_line_start and top_line_end:
        cv2.line(
            annotated,
            (int(round(top_line_start[0])), int(round(top_line_start[1]))),
            (int(round(top_line_end[0])), int(round(top_line_end[1]))),
            top_color,
            3,
        )

    bottom_line_start = measurement.get("bottom_line_start")
    bottom_line_end = measurement.get("bottom_line_end")
    if bottom_line_start and bottom_line_end:
        cv2.line(
            annotated,
            (int(round(bottom_line_start[0])), int(round(bottom_line_start[1]))),
            (int(round(bottom_line_end[0])), int(round(bottom_line_end[1]))),
            bottom_color,
            3,
        )

    cv2.putText(
        annotated,
        "PART AXIS",
        (max(12, x), max(28, y - 12)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        box_color,
        2,
        cv2.LINE_AA,
    )

    length_mm = measurement.get("length_mm")
    if length_mm is not None:
        length_label_pos = _clamp_text_origin(pt2[0] + 10, pt2[1] - 10)
        cv2.putText(
            annotated,
            f"LENGTH {float(length_mm):.2f} mm",
            length_label_pos,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            length_color,
            2,
            cv2.LINE_AA,
        )

    top_width_mm = measurement.get("top_width_mm")
    if top_width_mm is not None:
        top_label_pos = _line_end_label_pos(top_line_start, top_line_end)
        if top_label_pos is None:
            top_label_pos = _clamp_text_origin(x + w + 10, y + 24)
        cv2.putText(
            annotated,
            f"TOP {float(top_width_mm):.2f} mm",
            top_label_pos,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            top_color,
            2,
            cv2.LINE_AA,
        )

    bottom_width_mm = measurement.get("bottom_width_mm")
    if bottom_width_mm is not None:
        bottom_label_pos = _line_end_label_pos(bottom_line_start, bottom_line_end)
        if bottom_label_pos is None:
            bottom_label_pos = _clamp_text_origin(x + w + 10, y + h - 12)
        cv2.putText(
            annotated,
            f"BOTTOM {float(bottom_width_mm):.2f} mm",
            bottom_label_pos,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            bottom_color,
            2,
            cv2.LINE_AA,
        )

    if saved_label:
        color = (0, 0, 255) if str(saved_label).upper().startswith("NG") else (0, 170, 0)
        cv2.rectangle(annotated, (18, 18), (300, 60), color, -1)
        cv2.putText(
            annotated,
            str(saved_label),
            (28, 45),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

    return annotated
