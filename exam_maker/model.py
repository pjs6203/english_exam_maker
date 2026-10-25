from __future__ import annotations

import copy
import json
import re
from decimal import Decimal, InvalidOperation
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

    def validate_text(value: Any, location: str) -> None:
        from .markup import to_reportlab_markup

        if not isinstance(value, str) or not value.strip():
            raise ExamInputError(f"{location} must be a non-empty string.")
        try:
            to_reportlab_markup(value)
        except ExamInputError as exc:
            raise ExamInputError(f"{location}: {exc}") from exc

    def validate_question(question: Any, location: str, *, passage: str = "", instruction: str = "") -> None:
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

        validate_text(question.get("stem"), f"{location}.stem")
        _normalize_points(question, location, warnings)
        _normalize_segments(question, location)
        answer_format = question.get("answer_format", "auto")
        if answer_format not in ("auto", "inline", "options"):
            raise ExamInputError(f"{location}.answer_format must be auto, inline, or options.")
        if (answer_format == "auto" and passage
                and resolved_answer_format({"stem": passage}) == "inline"
                and _GRAMMAR.search(question["stem"] + " " + instruction)):
            question["answer_format"] = "inline"
        if "context" in question:
            validate_text(question["context"], f"{location}.context")
        for segment_index, segment in enumerate(question.get("segments", [])):
            validate_text(segment.get("text"), f"{location}.segments[{segment_index}].text")
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
        for option_index, option in enumerate(options):
            validate_text(option, f"{location}.options[{option_index}]")
        if resolved_answer_format(question) == "inline" and options:
            warnings.append(
                f"{location}: separate options are hidden for numbered underlines "
                "(answer_format=inline); source options are preserved."
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
            for key in ("heading", "instruction"):
                if block.get(key):
                    validate_text(block[key], f"{location}.{key}")
        elif block_type == "question":
            validate_question(block, location)
        elif block_type == "reading":
            passage = block.get("passage")
            if not isinstance(passage, str) or not passage.strip():
                raise ExamInputError(f"{location}.passage must be non-empty.")
            validate_text(passage, f"{location}.passage")
            for key in ("heading", "instruction"):
                if block.get(key):
                    validate_text(block[key], f"{location}.{key}")
            questions = block.get("questions")
            if not isinstance(questions, list) or not questions:
                raise ExamInputError(f"{location}.questions must be non-empty.")
            for question_index, question in enumerate(questions):
                validate_question(
                    question, f"{location}.questions[{question_index}]",
                    passage=passage, instruction=block.get("instruction", ""),
                )

    notes = result.get("conversion_notes", [])
    if not isinstance(notes, list) or any(not isinstance(note, str) for note in notes):
        raise ExamInputError("conversion_notes must be an array of strings.")
    warnings.extend(f"Conversion note: {note}" for note in notes)

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
    if len(options) not in (4, 5):
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


# Only markers attached to underlined spans count as inline answer candidates.
_MARKER = r"(?:[①-⑩]|\([1-9]\)|[1-9][.)])"
_INLINE = re.compile(
    rf"(?P<before>{_MARKER})\s*\[\[u\]\]|\[\[u\]\]\s*(?P<inside>{_MARKER})"
    rf"|\[\[/u\]\]\s*(?P<after>[①-⑩])"
)
_GRAMMAR = re.compile(
    r"grammatical(?:ly)?\s+(?:incorrect|wrong|error)|grammar\s+(?:error|mistake)"
    r"|(?:문법|어법).*(?:틀린|잘못|오류|옳지|적절하지)", re.IGNORECASE
)


def resolved_answer_format(question: dict[str, Any]) -> str:
    configured = question.get("answer_format", "auto")
    if configured != "auto":
        return configured
    markers = []
    for match in _INLINE.finditer(question["stem"]):
        marker = next(value for value in match.groups() if value)
        if marker in "①②③④⑤⑥⑦⑧⑨⑩":
            markers.append("①②③④⑤⑥⑦⑧⑨⑩".index(marker) + 1)
        else:
            markers.append(int(re.search(r"\d+", marker).group()))
    return "inline" if len(set(markers)) >= 2 else "options"


_POINTS = r"\d+(?:\.\d+)?"
_POINT_SUFFIX = re.compile(
    rf"\s+(?:\[\s*(?P<bracket>{_POINTS})\s*점\s*\]|"
    rf"\(\s*(?P<paren>{_POINTS})\s*점\s*\)|(?P<bare>{_POINTS})\s*점)\s*$"
)


def _normalize_points(question: dict[str, Any], location: str, warnings: list[str]) -> None:
    suffix = _POINT_SUFFIX.search(question["stem"])
    suffix_value = next((v for v in suffix.groups() if v), None) if suffix else None
    raw = question.get("points", suffix_value)
    if raw is None:
        if "points" in question:
            raise ExamInputError(f"{location}.points must be a positive number; omit it when unknown.")
        return
    text = str(raw).strip()
    match = re.fullmatch(rf"(?:({_POINTS})|\[\s*({_POINTS})\s*점\s*\]|\(\s*({_POINTS})\s*점\s*\)|({_POINTS})\s*점)", text)
    if not match:
        raise ExamInputError(f"{location}.points must be a positive number (for example 2 or '[2점]').")
    try:
        value = Decimal(next(v for v in match.groups() if v))
        if not value.is_finite() or value <= 0:
            raise InvalidOperation
    except InvalidOperation as exc:
        raise ExamInputError(f"{location}.points must be a positive finite number.") from exc
    question["points"] = format(value.normalize(), "f")
    if suffix:
        if Decimal(suffix_value) != value:
            warnings.append(f"{location}: stem score differs from points; using points={question['points']}.")
        question["stem"] = question["stem"][:suffix.start()].rstrip()


_SEGMENT = re.compile(r"(?<!\w)(?:\((?P<paren>[A-Z])\)|\[(?P<bracket>[A-Z])\]|(?P<circled>[Ⓐ-Ⓩ]))\s*")
_REORDER = re.compile(r"reorder|arrange|\border\b|순서|배열", re.IGNORECASE)


def _normalize_segments(question: dict[str, Any], location: str) -> None:
    if "segments" not in question and _REORDER.search(question["stem"]):
        matches = list(_SEGMENT.finditer(question["stem"]))
        labels = [next(v for v in m.groups() if v) for m in matches]
        letters = [chr(ord('A') + ord(v) - ord('Ⓐ')) if 'Ⓐ' <= v <= 'Ⓩ' else v for v in labels]
        # Conservative legacy migration: an instruction followed by A, B, C...
        # Ambiguous labels remain unchanged; explicit segments never need guessing.
        if len(matches) >= 2 and letters == [chr(ord('A') + i) for i in range(len(matches))]:
            stem = question["stem"]
            texts = [stem[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(stem)].strip() for i, m in enumerate(matches)]
            instruction = stem[:matches[0].start()].strip()
            if instruction and _REORDER.search(instruction) and all(texts):
                question["stem"] = instruction
                question["segments"] = [{"label": m.group().strip(), "text": text} for m, text in zip(matches, texts)]
    if "segments" not in question:
        return
    segments = question["segments"]
    if not isinstance(segments, list) or len(segments) < 2:
        raise ExamInputError(f"{location}.segments must contain at least two labeled paragraphs.")
    labels = set()
    for index, segment in enumerate(segments):
        path = f"{location}.segments[{index}]"
        if not isinstance(segment, dict):
            raise ExamInputError(f"{path} must be an object.")
        label = segment.get("label")
        if not isinstance(label, str) or not re.fullmatch(r"[A-Z]|\([A-Z]\)|\[[A-Z]\]|[Ⓐ-Ⓩ]", label):
            raise ExamInputError(f"{path}.label must be A, (A), [A], or Ⓐ (A–Z).")
        letter = chr(ord('A') + ord(label) - ord('Ⓐ')) if len(label) == 1 and 'Ⓐ' <= label <= 'Ⓩ' else label.strip("()[]")
        if letter in labels:
            raise ExamInputError(f"{path}.label duplicates {letter}.")
        labels.add(letter)

