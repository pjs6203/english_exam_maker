from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


class ExamInputError(ValueError):
    """Raised when the exam JSON does not match the supported structure."""


DEFAULT_DOCUMENT = {
    "title": "English Examination",
    "subtitle": "Question Paper",
    "form": "A",
    "subject": "English",
    "duration_minutes": 60,
    "exam_code": "ENG",
    "first_page_number": 1,
    "show_header": False,
    "show_candidate_table": False,
    "series_title": "D-SERIES 006",
    "series_title_every_page": True,
}

DEFAULT_STYLE = {
    "font_family": "Times New Roman",
    "font_size": 9.5,
    "leading": 11.7,
    "section_font_size": 9.7,
    "margin_left_mm": 19.0,
    "margin_right_mm": 19.0,
    "margin_top_mm": 15.0,
    "margin_bottom_mm": 16.0,
    "column_gap_mm": 5.0,
    "column_rule": True,
    "question_option_gap_pt": 3.5,
    "question_gap_pt": 8.5,
}


def load_exam(path: str | Path) -> tuple[dict[str, Any], list[str]]:
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ExamInputError(
            f"JSON syntax error at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise ExamInputError(f"Cannot read input file: {source}") from exc
    return normalize_exam(data)


def normalize_exam(data: Any) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(data, dict):
        raise ExamInputError("The JSON root must be an object.")

    result = copy.deepcopy(data)
    warnings: list[str] = []

    document = result.setdefault("document", {})
    if not isinstance(document, dict):
        raise ExamInputError("document must be an object.")
    for key, value in DEFAULT_DOCUMENT.items():
        document.setdefault(key, value)

    style = result.setdefault("style", {})
    if not isinstance(style, dict):
        raise ExamInputError("style must be an object.")
    for key, value in DEFAULT_STYLE.items():
        style.setdefault(key, value)

    blocks = result.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ExamInputError("blocks must be a non-empty array.")

    seen_numbers: set[str] = set()
    previous_numeric: int | None = None

    def validate_question(question: Any, location: str) -> None:
        nonlocal previous_numeric
        if not isinstance(question, dict):
            raise ExamInputError(f"{location} must be an object.")
        if "number" not in question:
            raise ExamInputError(f"{location}.number is required.")
        number_text = str(question["number"])
        if number_text in seen_numbers:
            warnings.append(f"Duplicate question number: {number_text}")
        seen_numbers.add(number_text)
        if isinstance(question["number"], int):
            if previous_numeric is not None and question["number"] < previous_numeric:
                warnings.append(
                    f"Question numbers are not ascending near {question['number']}."
                )
            previous_numeric = question["number"]

        stem = question.get("stem")
        if not isinstance(stem, str) or not stem.strip():
            raise ExamInputError(f"{location}.stem must be a non-empty string.")
        options = question.get("options", [])
        if not isinstance(options, list):
            raise ExamInputError(f"{location}.options must be an array.")
        if options and len(options) < 2:
            warnings.append(f"{location} has fewer than two options.")
        for option_index, option in enumerate(options):
            if not isinstance(option, str) or not option.strip():
                raise ExamInputError(
                    f"{location}.options[{option_index}] must be a non-empty string."
                )
        columns = question.get("options_columns", "auto")
        if columns not in (1, 2, "auto"):
            raise ExamInputError(
                f"{location}.options_columns must be 1, 2, or 'auto'."
            )

    for index, block in enumerate(blocks):
        location = f"blocks[{index}]"
        if not isinstance(block, dict):
            raise ExamInputError(f"{location} must be an object.")
        block_type = block.get("type")
        if block_type not in {"section", "question", "reading", "page_break"}:
            raise ExamInputError(
                f"{location}.type must be section, question, reading, or page_break."
            )
        if block_type == "section":
            if not (block.get("heading") or block.get("instruction")):
                raise ExamInputError(
                    f"{location} needs a heading or instruction."
                )
        elif block_type == "question":
            validate_question(block, location)
        elif block_type == "reading":
            passage = block.get("passage")
            if not isinstance(passage, str) or not passage.strip():
                raise ExamInputError(f"{location}.passage must be non-empty.")
            questions = block.get("questions")
            if not isinstance(questions, list) or not questions:
                raise ExamInputError(f"{location}.questions must be non-empty.")
            for question_index, question in enumerate(questions):
                validate_question(
                    question, f"{location}.questions[{question_index}]"
                )

    if style["font_family"].lower() != "times new roman":
        warnings.append(
            "font_family is not Times New Roman; the renderer currently uses its registered exam font family."
        )

    return result, warnings


def choose_option_columns(question: dict[str, Any]) -> int:
    configured = question.get("options_columns", "auto")
    if configured in (1, 2):
        return int(configured)
    options = question.get("options", [])
    if len(options) != 4:
        return 1
    visible_lengths = [len(_strip_markup(option)) for option in options]
    return 2 if max(visible_lengths, default=0) <= 42 else 1


def _strip_markup(value: str) -> str:
    for token in (
        "[[u]]",
        "[[/u]]",
        "[[b]]",
        "[[/b]]",
        "[[i]]",
        "[[/i]]",
    ):
        value = value.replace(token, "")
    return value
