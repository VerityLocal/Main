"""Opt-in integration tests against the actual isolated parser and local OCR."""

from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from backend.analysis.extraction import extract_pdf
from backend.analysis.segmentation import segment_document
from backend.config import PROJECT_ROOT, Settings


@unittest.skipUnless(os.getenv('PDF_AI_RUN_LOCAL_TOOLS') == '1', 'Opt in with PDF_AI_RUN_LOCAL_TOOLS=1')
class LocalToolIntegrationTests(unittest.TestCase):
    def settings(self):
        return Settings(extraction_python=PROJECT_ROOT/'.venv-extraction/bin/python',
                        tesseract_command=str(PROJECT_ROOT/'.tools-ocr/bin/tesseract'),
                        tessdata_dir=PROJECT_ROOT/'.tools-ocr/share/tessdata')

    def scan(self, text):
        image = Image.new('RGB', (1200, 1600), 'white')
        font = ImageFont.truetype('/System/Library/Fonts/Menlo.ttc', 28)
        ImageDraw.Draw(image).multiline_text((70, 120), text, fill='black', font=font, spacing=12)
        output = BytesIO(); pdf = canvas.Canvas(output, pagesize=(600, 800))
        pdf.drawImage(ImageReader(image), 0, 0, width=600, height=800)
        pdf.showPage(); pdf.save(); image.close()
        return output.getvalue()

    def test_real_scanned_prose_ocr_and_geometry(self):
        text = ('We measured the voltage across the resistor.\n'
                'The laboratory results were recorded carefully.\n'
                'Our observations were compared with theory.\n')*8
        with TemporaryDirectory() as temp:
            path = Path(temp)/'scan.pdf'; path.write_bytes(self.scan(text))
            document = extract_pdf(path, self.settings())
        self.assertEqual(document.engine, 'pymupdf')
        self.assertTrue(document.pages[0].lines)
        self.assertTrue(all(line.method == 'ocr' for line in document.pages[0].lines))
        self.assertIn('measured', '\n'.join(line.text for line in document.pages[0].lines))
        self.assertEqual(document.pages[0].regions[0]['status'], 'ocr_extracted')
        for line in document.pages[0].lines:
            x0,y0,x1,y1 = line.bbox
            self.assertTrue(0 <= x0 < x1 <= 600 and 0 <= y0 < y1 <= 800)
            self.assertIsNotNone(line.confidence)

    def test_real_screenshot_code_is_visible_but_withheld(self):
        text = ('def sum_items(items):\n'
                '    total = 0\n'
                '    for item in items:\n'
                '        total += item\n'
                '    return total\n\n')*4
        with TemporaryDirectory() as temp:
            path = Path(temp)/'screenshot.pdf'; path.write_bytes(self.scan(text))
            document = extract_pdf(path, self.settings())
        segments = segment_document(document)
        self.assertTrue(any(item.kind == 'code' and item.reason == 'ocr_code_uncertain' for item in segments))
        self.assertFalse(any(item.kind == 'code' and not item.reason for item in segments))

    def test_isolated_native_extraction_without_ocr(self):
        output = BytesIO(); pdf = canvas.Canvas(output, pagesize=(600,800))
        pdf.drawString(48, 700, 'We measured the voltage across the resistor.')
        pdf.showPage(); pdf.save()
        with TemporaryDirectory() as temp:
            path=Path(temp)/'native.pdf'; path.write_bytes(output.getvalue())
            document=extract_pdf(path, self.settings())
        self.assertEqual(document.engine,'pymupdf')
        self.assertEqual(document.pages[0].lines[0].method,'native')
        self.assertTrue(document.pages[0].lines[0].text.strip().startswith('We measured'))
