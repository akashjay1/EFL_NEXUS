"""Local gate-pass recognition. Only a number beside a GATE PASS header qualifies."""

import csv
import io
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageOps


def runtime_directory():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets" / "grn_ocr"


def read_words(image, psm=11):
    runtime = runtime_directory()
    executable = runtime / "tesseract.exe"
    if not executable.is_file() or not (runtime / "tessdata" / "eng.traineddata").is_file():
        raise RuntimeError("OCR runtime is missing. Run prepare_grn_ocr.py or reinstall the complete NEXUS package.")
    with tempfile.TemporaryDirectory(prefix="nexus-grn-") as folder:
        source = Path(folder) / "input.png"
        image.save(source)
        process = subprocess.run(
            [str(executable), str(source), "stdout", "--tessdata-dir", str(runtime / "tessdata"),
             "-l", "eng", "--psm", str(psm), "tsv"],
            capture_output=True, timeout=35,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    if process.returncode:
        raise RuntimeError("Tesseract could not read the photo: " + process.stderr.decode("utf-8", "replace")[:300])
    words = []
    for row in csv.DictReader(io.StringIO(process.stdout.decode("utf-8", "replace")), delimiter="\t"):
        if row.get("text", "").strip() and row.get("level") == "5":
            words.append({"text": row["text"].strip(), "confidence": float(row["conf"]),
                          **{k: int(row[k]) for k in ("left", "top", "width", "height")}})
    return words


def header_anchors(words, size):
    """Match adjacent GATE / PASS words, including GATEPASS as one OCR token."""
    width, height = size
    anchors = []
    clean = lambda w: re.sub(r"[^A-Z]", "", w["text"].upper())
    for gate in words:
        if gate["top"] > height * .5:
            continue
        if clean(gate) == "GATEPASS":
            anchors.append((gate["left"], gate["top"], gate["left"] + gate["width"], gate["top"] + gate["height"]))
        if clean(gate) != "GATE":
            continue
        for word in words:
            gap = word["left"] - gate["left"] - gate["width"]
            if (clean(word) == "PASS" and 0 <= gap < max(width * .035, gate["height"] * 2)
                    and abs(word["top"] - gate["top"]) <= max(word["height"], gate["height"]) * .7):
                anchors.append((gate["left"], min(gate["top"], word["top"]),
                                word["left"] + word["width"], max(gate["top"] + gate["height"], word["top"] + word["height"])))
    return anchors


def deskew(image):
    import cv2
    import numpy as np
    gray = np.asarray(ImageOps.grayscale(image))
    lines = cv2.HoughLinesP(cv2.Canny(gray, 60, 160), 1, math.pi / 1800, 80,
                            minLineLength=max(90, image.width // 4), maxLineGap=30)
    angles = []
    if lines is not None:
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            angle = math.degrees(math.atan2(int(y2) - int(y1), int(x2) - int(x1)))
            if abs(angle) < 18:
                angles.append(angle)
    angle = float(np.median(angles)) if angles else 0
    return image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white") if abs(angle) > .3 else image


def extract_gatepass(path, output_directory):
    import zxingcpp
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    image.thumbnail((2200, 2200), Image.Resampling.LANCZOS)
    # Upscaling helps small printed header text. Original capture is retained separately.
    if max(image.size) < 1800:
        factor = min(2, 1800 / max(image.size))
        image = image.resize((round(image.width * factor), round(image.height * factor)), Image.Resampling.LANCZOS)
    warnings, candidates, barcode_values, crops = [], set(), set(), []
    selected = None
    for rotation in (0, 90, 180, 270):
        working = deskew(image.rotate(rotation, expand=True, fillcolor="white"))
        words = read_words(working)
        anchors = header_anchors(words, working.size)
        if not anchors:
            import cv2
            import numpy as np
            # Local thresholding handles paper shadows and white camera borders
            # that can cause whole-page binarization to discard the header.
            search = working.crop((0, 0, working.width, working.height // 2))
            gray = np.asarray(ImageOps.grayscale(search))
            threshold = Image.fromarray(cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                                              cv2.THRESH_BINARY, 41, 13))
            words = read_words(threshold)
            anchors = header_anchors(words, working.size)
        if not anchors:
            continue
        selected = working
        for left, top, right, bottom in anchors:
            h = bottom - top
            # OCR is limited to the same printed line immediately following the label.
            number_box = (right, max(0, top - h // 2), min(working.width, right + working.width // 3), min(working.height, bottom + h // 2))
            inline = [w for w in words if w["left"] >= right and w["left"] < number_box[2]
                      and abs(w["top"] + w["height"] / 2 - (top + bottom) / 2) < h * .8]
            inline.sort(key=lambda w: w["left"])
            # A NUMBER/ID label is a body form field, not the header value.
            if inline and re.sub(r"[^A-Z]", "", inline[0]["text"].upper()) in ("NUMBER", "NO", "ID"):
                continue
            eligible = [w for w in inline if re.fullmatch(r"[0-9]+", w["text"])]
            values = {w["text"] for w in eligible}
            for word in eligible:
                # Independently reread a tight digit crop. Disagreement is held
                # for review rather than silently trusting one OCR pass.
                padding = max(4, word["height"] // 3)
                tight = working.crop((max(0, word["left"] - padding), max(0, word["top"] - padding),
                                      min(working.width, word["left"] + word["width"] + padding),
                                      min(working.height, word["top"] + word["height"] + padding)))
                tight = tight.resize((tight.width * 2, tight.height * 2), Image.Resampling.LANCZOS)
                tight_text = " ".join(w["text"] for w in read_words(tight, psm=7)).strip()
                if re.fullmatch(r"[0-9]+", tight_text):
                    values.add(tight_text)
            local_words = read_words(working.crop(number_box), psm=7)
            local = " ".join(w["text"] for w in local_words).strip().strip(": ")
            if re.fullmatch(r"[0-9]+", local):
                values.add(local)
            candidates.update(values)
            if any(w["confidence"] < 60 for w in eligible):
                warnings.append("Low-confidence printed number; compare every digit with the photo.")
            header_box = (max(0, left - h), max(0, top - h), min(working.width, number_box[2] + h), min(working.height, bottom + h * 7))
            crops.append(header_box)
            # Small phone-photo barcodes can decode only after cropping and upscaling.
            # Translate crop coordinates back to the document before associating them.
            associated_barcodes = []
            header_image = working.crop(header_box)
            for scale in (1, 2, 3):
                enlarged = header_image.resize((header_image.width * scale, header_image.height * scale), Image.Resampling.BICUBIC)
                associated_barcodes.extend((barcode, scale, header_box[0], header_box[1]) for barcode in
                    zxingcpp.read_barcodes(enlarged, formats=zxingcpp.BarcodeFormat.LinearCodes))
            for barcode, scale, offset_x, offset_y in associated_barcodes:
                points = [barcode.position.top_left, barcode.position.top_right,
                          barcode.position.bottom_left, barcode.position.bottom_right]
                cx = sum(p.x for p in points) / (4 * scale) + offset_x
                cy = sum(p.y for p in points) / (4 * scale) + offset_y
                # Only the linear barcode beneath this label is evidence for the gate pass.
                if right - h <= cx <= number_box[2] and bottom <= cy <= bottom + h * 7:
                    if re.fullmatch(r"[0-9]+", barcode.text):
                        barcode_values.add(barcode.text)
        # Once the upright label is located, do not search other orientations for unrelated numbers.
        break
    working_path, header_path = "", ""
    if selected is not None:
        working_path = str(output / "oriented.png")
        selected.save(working_path)
        if crops:
            header_path = str(output / "header.png")
            selected.crop(crops[0]).save(header_path)
    all_values = candidates | barcode_values
    gatepass = next(iter(all_values)) if len(all_values) == 1 else ""
    if len(all_values) > 1:
        warnings.append("Conflicting or multiple readings. Enter the number from the photo manually.")
    elif not gatepass:
        warnings.append("No unambiguous gate pass beside the header. Enter it manually or retry with a clearer photo.")
    elif not barcode_values:
        warnings.append("Header barcode could not be read; verify the printed number.")
    elif not candidates:
        warnings.append("Only the header barcode was readable; verify the printed number.")
    return {"gatepass": gatepass, "ocr_candidates": sorted(candidates), "barcode_candidates": sorted(barcode_values),
            "warnings": list(dict.fromkeys(warnings)), "header_path": header_path, "working_path": working_path}
