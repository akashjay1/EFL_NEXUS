"""Local gate-pass recognition. Only a number beside a GATE PASS header qualifies."""

import csv
import io
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from PIL import Image, ImageOps


def runtime_directory():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets" / "grn_ocr"


RECOGNITION_VERSION = 'grn-header-v2'


def read_words(image, psm=11, deadline=None):
    runtime = runtime_directory()
    executable = runtime / "tesseract.exe"
    if not executable.is_file() or not (runtime / "tessdata" / "eng.traineddata").is_file():
        raise RuntimeError("OCR runtime is missing. Run prepare_grn_ocr.py or reinstall the complete NEXUS package.")
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError('Local OCR reached its document time limit.')
    with tempfile.TemporaryDirectory(prefix="nexus-grn-") as folder:
        source = Path(folder) / "input.png"
        image.save(source)
        process = subprocess.run(
            [str(executable), str(source), "stdout", "--tessdata-dir", str(runtime / "tessdata"),
             "-l", "eng", "--psm", str(psm), "tsv"],
            capture_output=True, timeout=max(.01, min(35, deadline - time.monotonic())) if deadline else 35,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    if process.returncode:
        raise RuntimeError("Tesseract could not read the photo: " + process.stderr.decode("utf-8", "replace")[:300])
    words = []
    for row in csv.DictReader(io.StringIO(process.stdout.decode("utf-8", "replace")), delimiter="\t"):
        if row.get("text", "").strip() and row.get("level") == "5":
            words.append({"text": row["text"].strip(), "confidence": float(row["conf"]),
                          **{k: int(row[k]) for k in ("left", "top", "width", "height")},
                          'line': tuple(row.get(k, '') for k in ('page_num', 'block_num', 'par_num', 'line_num'))})
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


def skew_angle(image):
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
    return float(np.median(angles)) if angles else 0


def deskew(image):
    angle = skew_angle(image)
    return image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white") if abs(angle) > .3 else image


def header_number_evidence(words, size):
    """Use spatial evidence only; never substitute other form fields or fix digits."""
    evidence = []
    for left, top, right, bottom in header_anchors(words, size):
        h = bottom - top
        inline = sorted((w for w in words if right <= w['left'] < min(size[0], right + min(size[0] / 3, h * 12))
                         and abs(w['top'] + w['height'] / 2 - (top + bottom) / 2) < h * .8),
                        key=lambda w: w['left'])
        if inline and re.sub(r'[^A-Z]', '', inline[0]['text'].upper()) in ('NUMBER', 'NO', 'ID'):
            continue
        previous = None
        for word in inline:
            # The next field can share the same baseline (for example a phone
            # number). Only the adjacent token/run belongs to this label.
            if previous is None and word['left']-right > max(h*6, size[0]*.06):
                break
            if previous is not None and word['left']-previous['left']-previous['width'] > h*2:
                break
            if re.fullmatch(r'[0-9]+', word['text']):
                evidence.append({**word, 'anchor': [left, top, right, bottom]})
                previous = word
            elif re.sub(r'[:\s]', '', word['text']):
                break
    return evidence


def image_variants(image):
    """Keep the unmodified image as evidence; try reversible contrast variants."""
    import cv2
    import numpy as np
    gray = ImageOps.grayscale(image)
    yield 'grayscale', gray
    yield 'contrast', ImageOps.autocontrast(gray, cutoff=1)
    array = np.asarray(gray)
    if min(array.shape) >= 3:
        block = min(41, min(array.shape) // 2 * 2 - 1)
        yield 'adaptive', Image.fromarray(cv2.adaptiveThreshold(
            array, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, max(3, block), 13))


def extract_gatepass(path, output_directory, timeout=10):
    """Find on a preview, recognize original pixels, and enforce a document budget."""
    import zxingcpp
    started = time.monotonic()
    deadline = started + timeout
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    with Image.open(path) as source:
        original = ImageOps.exif_transpose(source).convert("RGB")
    warnings, candidates, barcode_values, evidence = [], set(), set(), []
    working_path, header_path, selected_rotation = '', '', None
    header_box = None
    try:
        # Search the document's header half first. Try all plain orientations
        # before spending the budget on threshold variants of an unreadable one.
        # The usual form is portrait: prioritize portrait orientations without
        # excluding a landscape document from the remaining search.
        orientations = (0, 180, 90, 270) if original.height >= original.width else (90, 270, 0, 180)
        for rotation, thresholded in [(r, thresholded) for thresholded in (False, True) for r in orientations]:
            if time.monotonic() >= deadline:
                raise TimeoutError()
            rotated = original.rotate(rotation, expand=True, fillcolor='white')
            preview = rotated.copy()
            preview.thumbnail((2200, 2200), Image.Resampling.LANCZOS)
            angle = skew_angle(preview)
            working = rotated.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True,
                                     fillcolor='white') if abs(angle) > .3 else rotated
            preview = working.copy()
            preview.thumbnail((2200, 2200), Image.Resampling.LANCZOS)
            if max(preview.size) < 1800:
                factor = min(2, 1800 / max(preview.size))
                preview = preview.resize((round(preview.width * factor), round(preview.height * factor)), Image.Resampling.LANCZOS)
            search = preview.crop((0, 0, preview.width, preview.height // 2))
            if thresholded:
                search = list(image_variants(search))[-1][1]
            words = read_words(search, deadline=deadline)
            anchors = header_anchors(words, preview.size)
            if not anchors:
                continue
            selected_rotation = rotation
            working_path = str(output / 'oriented.png')
            working.save(working_path)
            sx, sy = working.width / preview.width, working.height / preview.height
            for anchor in anchors:
                left, top, right, bottom = anchor
                h = bottom - top
                # A body field labelled NUMBER/ID cannot become a header number.
                inline = sorted((w for w in words if right <= w['left'] < right + preview.width / 3
                                 and abs(w['top'] + w['height']/2 - (top+bottom)/2) < h*.8), key=lambda w: w['left'])
                if inline and re.sub(r'[^A-Z]', '', inline[0]['text'].upper()) in ('NUMBER', 'NO', 'ID'):
                    continue
                number_box = (right, max(0, top-h//2), min(preview.width, right+min(preview.width//3, h*12)), min(preview.height, bottom+h//2))
                # Linear codes and their quiet zones can be much wider than
                # the printed digits; do not clip them to the digit-only ROI.
                barcode_right = min(preview.width, right+preview.width//3)
                box = (max(0, left-h), max(0, top-h), min(preview.width, barcode_right+h), min(preview.height, bottom+h*7))
                native = lambda bounds: (max(0, round(bounds[0]*sx)), max(0, round(bounds[1]*sy)),
                                          min(working.width, round(bounds[2]*sx)), min(working.height, round(bounds[3]*sy)))
                native_header = native(box)
                header = working.crop(native_header)
                if not header_path:
                    header_path = str(output / 'header.png')
                    header.save(header_path)
                    header_box = list(native_header)
                # Barcode coordinates are checked against this specific header.
                for scale in (1, 2, 3):
                    if time.monotonic() >= deadline:
                        raise TimeoutError()
                    enlarged = header if scale == 1 else header.resize((header.width*scale, header.height*scale), Image.Resampling.BICUBIC)
                    for barcode in zxingcpp.read_barcodes(enlarged, formats=zxingcpp.BarcodeFormat.LinearCodes):
                        points = [barcode.position.top_left, barcode.position.top_right, barcode.position.bottom_left, barcode.position.bottom_right]
                        cx = (sum(p.x for p in points)/(4*scale)+native_header[0])/sx
                        cy = (sum(p.y for p in points)/(4*scale)+native_header[1])/sy
                        if right-h <= cx <= barcode_right and bottom <= cy <= bottom+h*7 and re.fullmatch(r'[0-9]+', barcode.text):
                            barcode_values.add(barcode.text)
                    if barcode_values:
                        break
                eligible = [w for w in header_number_evidence(words, preview.size) if w['anchor'] == list(anchor)]
                for word in eligible:
                    candidates.add(word['text'])
                    evidence.append({'source': 'local', 'value': word['text'], 'confidence': word['confidence'],
                                     'box': list(native((word['left'], word['top'], word['left']+word['width'], word['top']+word['height'])))})
                if any(w['confidence'] < 60 for w in eligible):
                    warnings.append('Low-confidence printed number; compare every digit with the photo.')
                # Tight original-resolution crops avoid losing small digits on large photos.
                digit_images = []
                for word in eligible:
                    padding = max(4, word['height']//3)
                    digit_images.append(working.crop(native((word['left']-padding, word['top']-padding,
                                                             word['left']+word['width']+padding, word['top']+word['height']+padding))))
                digit_images.append(working.crop(native(number_box)))
                for digit_image in digit_images:
                    if digit_image.height < 80:
                        factor = min(3, max(1, 80 / max(1, digit_image.height)))
                        digit_image = digit_image.resize((max(1, round(digit_image.width*factor)), max(1, round(digit_image.height*factor))), Image.Resampling.LANCZOS)
                    for variant_name, variant in [('original', digit_image), *image_variants(digit_image)]:
                        reread = read_words(variant, psm=7, deadline=deadline)
                        value = ' '.join(w['text'] for w in reread).strip().strip(': ')
                        if re.fullmatch(r'[0-9]+', value):
                            candidates.add(value)
                            confidence = min((w['confidence'] for w in reread), default=0)
                            evidence.append({'source': 'local', 'value': value, 'confidence': confidence, 'variant': variant_name})
                            if confidence < 60:
                                warnings.append('Low-confidence printed number; compare every digit with the photo.')
                        # Agreement with a spatially associated barcode is enough for this crop.
                        if value and barcode_values == {value} and candidates == {value}:
                            break
                        if variant_name == 'original' and value and candidates == {value} and all(w['confidence'] >= 60 for w in reread):
                            break
            break
    except (TimeoutError, subprocess.TimeoutExpired):
        warnings.append(f'Local OCR reached its {timeout:g}-second document time limit; review or use cloud OCR.')
    all_values = candidates | barcode_values
    gatepass = next(iter(all_values)) if len(all_values) == 1 else ''
    if len(all_values) > 1:
        warnings.append('Conflicting or multiple readings. Enter the number from the photo manually.')
    elif not gatepass:
        warnings.append('No unambiguous gate pass beside the header. Enter it manually or retry with a clearer photo.')
    elif not barcode_values:
        warnings.append('Header barcode could not be read; verify the printed number.')
    elif not candidates:
        warnings.append('Only the header barcode was readable; verify the printed number.')
    sources = (['local'] if candidates else []) + (['barcode'] if barcode_values else [])
    return {'gatepass': gatepass, 'ocr_candidates': sorted(candidates), 'barcode_candidates': sorted(barcode_values),
            'warnings': list(dict.fromkeys(warnings)), 'header_path': header_path, 'working_path': working_path,
            'recognition_source': ' + '.join(sources) or 'local', 'recognition_version': RECOGNITION_VERSION,
            'processing_status': 'local_complete', 'evidence': evidence, 'header_box': header_box,
            'rotation': selected_rotation, 'seconds': round(time.monotonic()-started, 3)}
