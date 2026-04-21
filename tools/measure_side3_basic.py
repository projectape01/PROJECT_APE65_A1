#!/usr/bin/env python3
import argparse
import sys

import cv2
import numpy as np


def load_image(image_path):
    """Load an image from disk and fail fast if the file cannot be read."""
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError(f"Cannot read image: {image_path}")
    return image


def create_binary_mask(gray_image):
    """Blur + threshold the image, then choose the binary polarity with the strongest main contour."""
    blurred = cv2.GaussianBlur(gray_image, (5, 5), 0)

    _, binary = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )
    _, binary_inv = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )

    mask_candidates = [binary, binary_inv]
    best_mask = None
    best_area = -1.0

    for mask in mask_candidates:
        contour = find_largest_contour(mask)
        if contour is None:
            continue
        area = cv2.contourArea(contour)
        if area > best_area:
            best_area = area
            best_mask = mask

    if best_mask is None:
        raise ValueError("No contour found after thresholding.")

    return blurred, best_mask


def find_largest_contour(binary_mask):
    """Return the largest external contour from a binary image."""
    contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


def build_contour_mask(image_shape, contour):
    """Create a filled mask for the detected part contour."""
    mask = np.zeros(image_shape[:2], dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, thickness=-1)
    return mask


def width_at_relative_height(mask, x, y, w, h, relative_y):
    """
    Measure part width on one horizontal row.

    The row is selected using a relative position inside the contour bounding box.
    """
    target_y = y + int(round((h - 1) * relative_y))
    target_y = max(0, min(mask.shape[0] - 1, target_y))

    row = mask[target_y]
    xs = np.where(row > 0)[0]
    if xs.size == 0:
        raise ValueError(f"No contour pixels found at y={target_y}.")

    x_min = int(xs.min())
    x_max = int(xs.max())
    width_px = int(x_max - x_min)

    return {
        "y": target_y,
        "x_min": x_min,
        "x_max": x_max,
        "width_px": width_px,
    }


def measure_part(contour, mask, scale_mm_per_pixel):
    """Measure LENGTH, TOP, and BOTTOM from the contour and convert them to mm."""
    x, y, w, h = cv2.boundingRect(contour)

    top = width_at_relative_height(mask, x, y, w, h, relative_y=0.25)
    bottom = width_at_relative_height(mask, x, y, w, h, relative_y=0.75)

    length_px = int(h)

    return {
        "bbox": (x, y, w, h),
        "length_px": length_px,
        "length_mm": length_px * scale_mm_per_pixel,
        "top_px": top["width_px"],
        "top_mm": top["width_px"] * scale_mm_per_pixel,
        "top_y": top["y"],
        "top_x_min": top["x_min"],
        "top_x_max": top["x_max"],
        "bottom_px": bottom["width_px"],
        "bottom_mm": bottom["width_px"] * scale_mm_per_pixel,
        "bottom_y": bottom["y"],
        "bottom_x_min": bottom["x_min"],
        "bottom_x_max": bottom["x_max"],
    }


def annotate_image(image, contour, measurement):
    """Draw contour, LENGTH/TOP/BOTTOM lines, and text labels on the image."""
    annotated = image.copy()
    x, y, w, h = measurement["bbox"]

    cv2.drawContours(annotated, [contour], -1, (0, 255, 0), 2)

    length_x = x + w // 2
    length_y1 = y
    length_y2 = y + h
    cv2.line(annotated, (length_x, length_y1), (length_x, length_y2), (0, 0, 255), 2)
    cv2.putText(
        annotated,
        f"LENGTH: {measurement['length_mm']:.2f} mm",
        (length_x + 10, max(30, y + 20)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 0, 255),
        2,
        cv2.LINE_AA,
    )

    cv2.line(
        annotated,
        (measurement["top_x_min"], measurement["top_y"]),
        (measurement["top_x_max"], measurement["top_y"]),
        (0, 165, 255),
        2,
    )
    cv2.putText(
        annotated,
        f"TOP: {measurement['top_mm']:.2f} mm",
        (measurement["top_x_min"], max(30, measurement["top_y"] - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 165, 255),
        2,
        cv2.LINE_AA,
    )

    cv2.line(
        annotated,
        (measurement["bottom_x_min"], measurement["bottom_y"]),
        (measurement["bottom_x_max"], measurement["bottom_y"]),
        (255, 0, 0),
        2,
    )
    cv2.putText(
        annotated,
        f"BOTTOM: {measurement['bottom_mm']:.2f} mm",
        (measurement["bottom_x_min"], min(annotated.shape[0] - 10, measurement["bottom_y"] + 25)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 0, 0),
        2,
        cv2.LINE_AA,
    )

    return annotated


def print_measurement(measurement):
    """Print all measured values in both pixel and mm units."""
    print(f"LENGTH: {measurement['length_px']} px -> {measurement['length_mm']:.2f} mm")
    print(f"TOP:    {measurement['top_px']} px -> {measurement['top_mm']:.2f} mm")
    print(f"BOTTOM: {measurement['bottom_px']} px -> {measurement['bottom_mm']:.2f} mm")


def parse_args():
    parser = argparse.ArgumentParser(description="Measure SIDE3 part size from an image using OpenCV.")
    parser.add_argument("image_path", help="Path to the input image.")
    parser.add_argument(
        "--scale-mm-per-pixel",
        type=float,
        default=0.05,
        help="Scale factor for converting pixels to mm.",
    )
    parser.add_argument(
        "--output",
        default="side3_measurement_result.png",
        help="Path to save the annotated output image.",
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        help="Do not open an OpenCV display window.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    image = load_image(args.image_path)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary_mask = create_binary_mask(gray)

    contour = find_largest_contour(binary_mask)
    if contour is None:
        raise ValueError("No main contour found.")

    contour_mask = build_contour_mask(image.shape, contour)
    measurement = measure_part(contour, contour_mask, args.scale_mm_per_pixel)
    annotated = annotate_image(image, contour, measurement)

    print_measurement(measurement)

    if not cv2.imwrite(args.output, annotated):
        raise ValueError(f"Failed to save output image: {args.output}")

    if not args.no_display:
        cv2.imshow("SIDE3 Measurement", annotated)
        cv2.waitKey(0)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
