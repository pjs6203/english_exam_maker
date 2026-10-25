import copy
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from pypdf import PdfReader

from exam_maker.model import ExamInputError, normalize_exam, resolved_answer_format
from exam_maker.renderer import ExamRenderer
from exam_maker.cli import main


def exam(question):
    return {"blocks": [{"type": "question", "number": 1, **question}]}


class QuestionFormatTests(unittest.TestCase):
    def test_ai_variants_produce_identical_inline_papers(self):
        stem = "They ①[[u]]is[[/u]] ready, but ②[[u]]he[[/u]] is late."
        variants = [{}, {"options": []}, {"options": ["is", "he"]}]
        papers = []
        with tempfile.TemporaryDirectory() as folder:
            for index, variant in enumerate(variants):
                data = exam({"stem": stem, **variant})
                original = copy.deepcopy(data)
                output = Path(folder) / f"variant-{index}.pdf"
                ExamRenderer(data).render(output)
                papers.append(PdfReader(output).pages[0].extract_text())
                self.assertEqual(original, data)
        self.assertEqual(papers[0], papers[1])
        self.assertEqual(papers[0], papers[2])

    def test_inline_detection_variants_and_explicit_override(self):
        for stem in (
            "①[[u]]one[[/u]] and ②[[u]]two[[/u]]",
            "[[u]]①one[[/u]] and [[u]]②two[[/u]]",
            "(1) [[u]]one[[/u]] and (2) [[u]]two[[/u]]",
            "1. [[u]]one[[/u]] and 2. [[u]]two[[/u]]",
            "[[u]]one[[/u]]① and [[u]]two[[/u]]②",
        ):
            with self.subTest(stem=stem):
                self.assertEqual("inline", resolved_answer_format({"stem": stem}))
                self.assertEqual("options", resolved_answer_format({"stem": stem, "answer_format": "options"}))

    def test_vocabulary_underline_keeps_choices(self):
        for stem in ("A [[u]]word[[/u]].", "①[[u]]one[[/u]]", "①plain ②text", "①[[u]]one[[/u]] ①[[u]]again[[/u]]"):
            self.assertEqual("options", resolved_answer_format({"stem": stem}))

    def test_source_options_are_preserved_and_warning_survives_normalization(self):
        data, warnings = normalize_exam(exam({"stem": "①[[u]]a[[/u]] ②[[u]]b[[/u]]", "options": ["a", "b"]}))
        again, again_warnings = normalize_exam(data)
        self.assertEqual(["a", "b"], data["blocks"][0]["options"])
        self.assertEqual(data, again)
        self.assertEqual(warnings, again_warnings)
        self.assertTrue(any("hidden" in warning for warning in warnings))

    def test_reading_subquestion_can_use_inline_format(self):
        data, _ = normalize_exam({"blocks": [{"type": "reading", "passage": "①[[u]]a[[/u]] ②[[u]]b[[/u]]", "questions": [{"number": 1, "stem": "Identify the error.", "answer_format": "inline", "options": []}]}]})
        self.assertEqual("inline", resolved_answer_format(data["blocks"][0]["questions"][0]))

    def test_shared_passage_grammar_inference_keeps_other_reading_choices(self):
        data, warnings = normalize_exam({"blocks": [{
            "type": "reading", "passage": "①[[u]]a[[/u]] ②[[u]]b[[/u]]",
            "questions": [
                {"number": 1, "stem": "Identify the grammatical error.", "options": ["a", "b"]},
                {"number": 2, "stem": "What is the main idea?", "options": ["Idea one", "Idea two"]},
            ],
        }]})
        questions = data["blocks"][0]["questions"]
        self.assertEqual("inline", resolved_answer_format(questions[0]))
        self.assertEqual("options", resolved_answer_format(questions[1]))
        self.assertEqual(1, len(warnings))

    def test_legacy_reorder_preserves_all_words_and_labels(self):
        for labels in (("(A)", "(B)", "(C)"), ("Ⓐ", "Ⓑ", "Ⓒ"), ("[A]", "[B]", "[C]")):
            stem = "Reorder the paragraphs. " + " ".join(label + text for label, text in zip(labels, ["Alpha.", "Beta.", "Gamma."]))
            data, _ = normalize_exam(exam({"stem": stem}))
            q = data["blocks"][0]
            self.assertEqual("Reorder the paragraphs.", q["stem"])
            self.assertEqual(list(labels), [s["label"] for s in q["segments"]])
            self.assertEqual(["Alpha.", "Beta.", "Gamma."], [s["text"] for s in q["segments"]])
            self.assertEqual(data, normalize_exam(data)[0])

    def test_ambiguous_reorder_and_ordinary_references_unchanged(self):
        for stem in ("Reorder this: (A) Alpha. (C) Gamma.", "The categories (A) and (B) are examples."):
            data, _ = normalize_exam(exam({"stem": stem}))
            self.assertEqual(stem, data["blocks"][0]["stem"])
            self.assertNotIn("segments", data["blocks"][0])

    def test_points_from_ai_strings_and_legacy_stems(self):
        for score in (2, 2.0, "2", "2점", "[2점]", "(2점)"):
            with self.subTest(score=score):
                data, _ = normalize_exam(exam({"stem": "Question. 2점", "points": score}))
                self.assertEqual("2", data["blocks"][0]["points"])
                self.assertEqual("Question.", data["blocks"][0]["stem"])
        for suffix in ("[2.5점]", "(2.5점)", "2.5점"):
            data, _ = normalize_exam(exam({"stem": f"Question. {suffix}"}))
            self.assertEqual("2.5", data["blocks"][0]["points"])

    def test_only_terminal_korean_score_is_migrated(self):
        stem = "A score of 2점 was recorded in 2025."
        data, _ = normalize_exam(exam({"stem": stem}))
        self.assertNotIn("points", data["blocks"][0])
        self.assertEqual(stem, data["blocks"][0]["stem"])

    def test_conflicting_score_warns_and_prints_once(self):
        data, warnings = normalize_exam(exam({"stem": "Question. [3점]", "points": 2}))
        self.assertEqual("Question.", data["blocks"][0]["stem"])
        self.assertTrue(any("differs" in w for w in warnings))

    def test_invalid_structured_fields_have_actionable_errors(self):
        for fields in (
            {"points": True}, {"points": -2}, {"points": "NaN"}, {"points": 0}, {"points": None},
            {"answer_format": "unknown"}, {"context": ""},
            {"segments": []}, {"segments": [{"label": "A", "text": "a"}, {"label": "(A)", "text": "b"}]},
            {"segments": [{"label": "A", "text": "a"}, {"label": "B"}]},
        ):
            with self.subTest(fields=fields), self.assertRaises(ExamInputError):
                normalize_exam(exam({"stem": "Question.", **fields}))

    def test_validate_catches_markup_in_all_question_fields(self):
        for fields in (
            {"stem": "[[u]]broken"}, {"context": "[[b]]broken"},
            {"options": ["ok", "[[i]]broken"]},
            {"segments": [{"label": "A", "text": "[[u]]broken"}, {"label": "B", "text": "ok"}]},
        ):
            with self.subTest(fields=fields), self.assertRaisesRegex(ExamInputError, r"blocks\[0\]"):
                normalize_exam(exam({"stem": "Question.", **fields}))

    def test_conversion_notes_visible_to_validator(self):
        data = exam({"stem": "Question."})
        data["conversion_notes"] = ["Check the source at question 1."]
        self.assertIn("Conversion note: Check the source at question 1.", normalize_exam(data)[1])

    def test_boxes_segments_scores_and_five_choices_reach_pdf(self):
        data = exam({"stem": "Reorder the paragraphs.", "context": "Given paragraph.", "points": 4,
                     "segments": [{"label": "(A)", "text": "Alpha text."}, {"label": "(B)", "text": "Beta text."}],
                     "options": ["A-B", "B-A", "A-A", "B-B", "B-A-B"]})
        renderer = ExamRenderer(data)
        q = renderer.data["blocks"][0]
        flowables = renderer._question_flowables(q, include_gap=False)
        self.assertEqual(2, flowables[-1]._ncols)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "structured.pdf"
            renderer.render(output)
            text = PdfReader(output).pages[0].extract_text()
        for fragment in ("Given paragraph.", "Alpha text.", "Beta text.", "[4점]", "⑤"):
            self.assertIn(fragment, text)

    def test_wide_options_do_not_get_cramped_auto_columns(self):
        data = exam({"stem": "Select.", "options": ["W" * 35] * 5})
        renderer = ExamRenderer(data)
        flowables = renderer._question_flowables(renderer.data["blocks"][0], include_gap=False)
        self.assertTrue(all(not hasattr(flowable, '_ncols') for flowable in flowables))

    def test_long_segments_can_span_columns_without_losing_text(self):
        data = exam({"stem": "Reorder the paragraphs.", "segments": [
            {"label": "(A)", "text": "Alpha begins. " + "Readers connect evidence with ideas. " * 75 + "Alpha ends."},
            {"label": "(B)", "text": "Beta begins. " + "Writers organize ideas for readers. " * 35 + "Beta ends."},
        ], "options": ["A-B", "B-A"]})
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "long.pdf"
            result = ExamRenderer(data).render(output)
            text = "\n".join(p.extract_text() for p in PdfReader(output).pages)
        self.assertEqual(1, result.page_count)
        self.assertEqual(2, result.placements[0].column_end)
        text = " ".join(text.split())
        self.assertEqual(75, text.count("Readers connect evidence with ideas."))
        for fragment in ("Alpha begins.", "Alpha ends.", "Beta begins.", "Beta ends."):
            self.assertIn(fragment, text)

    def test_cli_render_retains_first_pass_diagnostics(self):
        import json

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "input.json"
            source.write_text(json.dumps(exam({"stem": "Question. 3점", "points": 2})))
            log = StringIO()
            with redirect_stdout(log):
                code = main(["render", str(source), "-o", str(Path(folder) / "exam.pdf")])
        self.assertEqual(0, code)
        self.assertIn("stem score differs", log.getvalue())


if __name__ == "__main__":
    unittest.main()
