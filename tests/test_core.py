from pathlib import Path
import tempfile
import unittest

from pypdf import PdfReader
from reportlab.lib.enums import TA_LEFT

from exam_maker.markup import to_reportlab_markup
from exam_maker.model import ExamInputError, load_exam, normalize_exam
from exam_maker.renderer import ExamRenderer


ROOT = Path(__file__).resolve().parent.parent


class MarkupTests(unittest.TestCase):
    def test_supported_markup(self):
        result = to_reportlab_markup(
            "A [[blank:4]] and [[u]]word[[/u]] with [[b]]weight[[/b]]."
        )
        self.assertIn("<u", result)
        self.assertIn("word</u>", result)
        self.assertIn("<b>weight</b>", result)

    def test_unbalanced_markup_rejected(self):
        with self.assertRaises(ExamInputError):
            to_reportlab_markup("[[u]]broken")


class RenderingTests(unittest.TestCase):
    def test_regular_section_is_left_aligned(self):
        data, _ = load_exam(ROOT / "examples" / "sample_exam.json")
        renderer = ExamRenderer(data)
        block = renderer._section_block(
            {
                "type": "section",
                "heading": "[1]",
                "instruction": "Choose the best one.",
                "align": "center",
            },
            "test-section",
        )
        self.assertEqual(TA_LEFT, block.flowables[0].style.alignment)

    def test_choices_begin_after_question_number(self):
        data, _ = load_exam(ROOT / "examples" / "sample_exam.json")
        renderer = ExamRenderer(data)
        question = {
            "number": 14,
            "stem": "A sentence.",
            "options": ["First long option.", "Second long option."],
            "options_columns": 1,
        }
        flowables = renderer._question_flowables(question, include_gap=False)
        first_option = flowables[2]
        self.assertEqual(3.5, flowables[1].height)
        self.assertGreater(first_option.style.bulletIndent, 0)
        self.assertGreater(first_option.style.leftIndent, first_option.style.bulletIndent)

    def test_sample_validates_and_renders(self):
        data, warnings = load_exam(ROOT / "examples" / "sample_exam.json")
        self.assertEqual([], warnings)
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "sample.pdf"
            manifest = Path(temp_dir) / "layout.json"
            result = ExamRenderer(data).render(output, layout_manifest_path=manifest)
            self.assertTrue(output.exists())
            self.assertTrue(manifest.exists())
            self.assertGreaterEqual(result.page_count, 2)
            reader = PdfReader(output)
            self.assertEqual(result.page_count, len(reader.pages))
            extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
            self.assertIn("Despite the chaos", extracted)
            self.assertIn("compunction", extracted)
            self.assertIn("According to the passage", extracted)
            self.assertNotIn("Department", reader.pages[0].extract_text() or "")
            self.assertNotIn("Candidate No.", reader.pages[0].extract_text() or "")
            self.assertIn("D-SERIES 006", reader.pages[0].extract_text() or "")
            self.assertIn("D-SERIES 006", reader.pages[1].extract_text() or "")
            reading = next(p for p in result.placements if p.block_id == "reading-31-32")
            self.assertEqual(reading.page_start, reading.page_end)
            self.assertEqual(2, reading.column_end)


if __name__ == "__main__":
    unittest.main()
