"""Real local OCR checks against clearly labelled generated document test doubles.

Set NEXUS_GRN_SAMPLE to the supplied photo's local path to additionally run its
ground-truth check. No customer photographs are committed to this repository.
"""

import os
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw, ImageFont

from grn_ocr import extract_gatepass, runtime_directory


@unittest.skipUnless((runtime_directory() / "tesseract.exe").exists(), "Prepare the local OCR runtime first")
class OCRSafetyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def document_double(self, label="GATE PASS:", number="000123", barcode=None):
        """Generated document test double; never used as production input."""
        font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 32)
        image = Image.new("RGB", (1100, 1400), "white")
        draw = ImageDraw.Draw(image)
        draw.text((100, 30), "TEST DOUBLE — NOT A REAL DOCUMENT", font=font, fill="black")
        draw.text((420, 130), label, font=font, fill="black")
        draw.text((650, 130), number, font=font, fill="black")
        draw.text((50, 600), "APPOINTMENT ID: 987654", font=font, fill="black")
        if barcode:
            import zxingcpp
            code = Image.fromarray(zxingcpp.create_barcode(barcode, zxingcpp.BarcodeFormat.Code39).to_image(scale=3))
            image.paste(code.convert("RGB"), (625, 200))
        path = self.directory / "document-test-double.png"
        image.save(path)
        return path

    def test_unrelated_number_has_no_gatepass(self):
        result = extract_gatepass(self.document_double("DATE:", "734355"), self.directory / "result")
        self.assertEqual(result["gatepass"], "")

    def test_body_gatepass_field_is_not_used_as_header(self):
        path = self.document_double("DATE:", "734355")
        with Image.open(path) as source:
            image = source.copy()
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 32)
        draw.text((200, 1100), "GATE PASS: 999888", font=font, fill="black")
        image.save(path)
        result = extract_gatepass(path, self.directory / "result")
        self.assertEqual(result["gatepass"], "")

    def test_printed_number_keeps_leading_zeroes(self):
        result = extract_gatepass(self.document_double(), self.directory / "result")
        self.assertEqual(result["gatepass"], "000123")

    def test_conflicting_header_barcode_requires_manual_entry(self):
        result = extract_gatepass(self.document_double(barcode="999888"), self.directory / "result")
        self.assertIn("000123", result["ocr_candidates"])
        self.assertIn("999888", result["barcode_candidates"])
        self.assertEqual(result["gatepass"], "")

    @unittest.skipUnless(os.environ.get("NEXUS_GRN_SAMPLE"), "Set NEXUS_GRN_SAMPLE to the supplied photo")
    def test_supplied_photo_is_734355(self):
        result = extract_gatepass(os.environ["NEXUS_GRN_SAMPLE"], self.directory / "sample")
        self.assertEqual(result["gatepass"], "734355")


if __name__ == "__main__":
    unittest.main()
