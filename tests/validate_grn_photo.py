"""Measure one real photo and clearly labelled transformations; never an accuracy estimate.

python tests/validate_grn_photo.py PHOTO_PATH OUTPUT_DIRECTORY
"""

import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFilter, ImageOps
import numpy as np

from grn_ocr import deskew, extract_gatepass, header_anchors, read_words


def validate(photo, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with Image.open(photo) as source:
        original = ImageOps.exif_transpose(source).convert("RGB")
    array = np.array(original).astype(float)
    shadow = np.linspace(.45, 1, original.width)[None, :, None]
    frame = Image.new("RGB", (original.width + 200, original.height + 250), "white")
    frame.paste(original, (140, 150))
    variants = {"original": original, "rotate90": original.rotate(90, expand=True),
                "rotate180": original.rotate(180, expand=True), "rotate270": original.rotate(270, expand=True),
                "tilt8": original.rotate(8, expand=True, fillcolor="white"),
                "shadow": Image.fromarray(np.uint8(np.clip(array * shadow, 0, 255))),
                "mild_blur": original.filter(ImageFilter.GaussianBlur(.6)), "different_framing": frame}
    no_barcode = deskew(original)
    no_barcode = no_barcode.resize((no_barcode.width * 2, no_barcode.height * 2), Image.Resampling.LANCZOS)
    anchors = header_anchors(read_words(no_barcode), no_barcode.size)
    if anchors:
        left, top, right, bottom = anchors[0]
        h = bottom - top
        ImageDraw.Draw(no_barcode).rectangle((right-h, bottom+h*.4, min(no_barcode.width, right+no_barcode.width//3), bottom+h*5), fill="white")
        variants["barcode_masked"] = no_barcode
    results = []
    for name, image in variants.items():
        path = output / (name + ".png")
        image.save(path)
        started = time.monotonic()
        result = extract_gatepass(path, output / name)
        row = {"case": name, "transformed": name != "original", "expected": "734355",
               "seconds": round(time.monotonic()-started, 2), **result}
        results.append(row)
        print(json.dumps(row), flush=True)
        (output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


if __name__ == "__main__":
    validate(sys.argv[1], sys.argv[2])
