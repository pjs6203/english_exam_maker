from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from reportlab.platypus import Flowable, Paragraph, Spacer, Table, TableStyle

from .fonts import register_exam_fonts
from .markup import to_reportlab_markup
from .model import choose_option_columns, normalize_exam, resolved_answer_format


class LayoutError(RuntimeError):
    """Raised when a single reading group cannot fit on one two-column page."""


@dataclass
class RenderBlock:
    block_id: str
    kind: str
    flowables: list[Flowable]
    start_at_column_top: bool = False
    allow_across_columns: bool = False


@dataclass
class Placement:
    block_id: str
    kind: str
    page_start: int
    column_start: int
    page_end: int
    column_end: int


@dataclass
class RenderResult:
    output_path: Path
    page_count: int
    warnings: list[str] = field(default_factory=list)
    placements: list[Placement] = field(default_factory=list)


class QuestionGroupFlowable(Flowable):
    """Keeps a reading sub-question together when it fits one column."""

    def __init__(
        self,
        flowables: list[Flowable],
        column_width: float,
        column_height: float,
    ):
        super().__init__()
        self.flowables = flowables
        self.column_width = column_width
        self.column_height = column_height
        self._heights: list[float] = []

    def wrap(self, avail_width: float, avail_height: float):
        self._heights = [
            flowable.wrap(avail_width, 100000)[1] for flowable in self.flowables
        ]
        self.width = avail_width
        self.height = sum(self._heights)
        return self.width, self.height

    def draw(self):
        y = self.height
        for flowable, height in zip(self.flowables, self._heights):
            y -= height
            flowable.drawOn(self.canv, 0, y)

    def split(self, avail_width: float, avail_height: float):
        _, total_height = self.wrap(avail_width, avail_height)
        if total_height <= self.column_height:
            return []
        return list(self.flowables)


class ExamRenderer:
    def __init__(self, data: dict[str, Any]):
        self.data, self.input_warnings = normalize_exam(data)
        self.document = self.data["document"]
        self.config = self.data["style"]
        self.font_registration = register_exam_fonts()
        self.page_width, self.page_height = A4

        self.left_margin = float(self.config["margin_left_mm"]) * mm
        self.right_margin = float(self.config["margin_right_mm"]) * mm
        self.top_margin = float(self.config["margin_top_mm"]) * mm
        self.bottom_margin = float(self.config["margin_bottom_mm"]) * mm
        self.column_gap = float(self.config["column_gap_mm"]) * mm
        content_width = self.page_width - self.left_margin - self.right_margin
        self.column_width = (content_width - self.column_gap) / 2
        self.column_x = [
            self.left_margin,
            self.left_margin + self.column_width + self.column_gap,
        ]

        body_size = float(self.config["font_size"])
        leading = float(self.config["leading"])
        section_size = float(self.config["section_font_size"])
        self.body_style = ParagraphStyle(
            "Body",
            fontName="ExamRoman",
            fontSize=body_size,
            leading=leading,
            textColor=colors.black,
            alignment=TA_LEFT,
            spaceAfter=0,
            splitLongWords=False,
            allowWidows=0,
            allowOrphans=0,
        )
        self.passage_style = ParagraphStyle(
            "Passage",
            parent=self.body_style,
            alignment=TA_JUSTIFY,
        )
        self.section_style = ParagraphStyle(
            "Section",
            parent=self.body_style,
            fontSize=section_size,
            leading=max(leading, section_size * 1.2),
            alignment=TA_LEFT,
        )
        self.placements: list[Placement] = []
        self.warnings = list(self.input_warnings) + list(
            self.font_registration.warnings
        )

    def render(
        self,
        output_path: str | Path,
        *,
        layout_manifest_path: str | Path | None = None,
    ) -> RenderResult:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        self.canvas = canvas.Canvas(str(output), pagesize=A4, pageCompression=1)
        self.canvas.setTitle(str(self.document.get("title", "English Examination")))
        self.page_number = 0
        self.column_index = 0
        self.cursor_y = 0.0
        self.body_top = 0.0
        self._open_page()

        blocks = self._build_blocks(self.data["blocks"])
        for index, block in enumerate(blocks):
            if block.kind == "page_break":
                self._new_page()
                continue

            if block.kind == "section" and index + 1 < len(blocks):
                next_block = blocks[index + 1]
                combined = self._measure(block.flowables) + self._measure(
                    next_block.flowables
                )
                if combined > self._remaining_height() and combined <= self._column_height():
                    self._advance_column()

            self._place_block(block)

        self.canvas.save()

        if layout_manifest_path is not None:
            manifest = Path(layout_manifest_path)
            manifest.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "pages": self.page_number,
                "warnings": self.warnings,
                "placements": [placement.__dict__ for placement in self.placements],
            }
            manifest.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        return RenderResult(
            output_path=output,
            page_count=self.page_number,
            warnings=self.warnings,
            placements=self.placements,
        )

    def _build_blocks(self, raw_blocks: list[dict[str, Any]]) -> list[RenderBlock]:
        result: list[RenderBlock] = []
        for index, raw in enumerate(raw_blocks):
            block_type = raw["type"]
            block_id = str(raw.get("id", f"block-{index + 1}"))
            if block_type == "page_break":
                result.append(RenderBlock(block_id, block_type, []))
            elif block_type == "section":
                result.append(self._section_block(raw, block_id))
            elif block_type == "question":
                flowables = self._question_flowables(raw, include_gap=True)
                result.append(
                    RenderBlock(
                        block_id=block_id,
                        kind="question",
                        flowables=flowables,
                        start_at_column_top=bool(
                            raw.get("start_at_column_top", False)
                        ),
                        allow_across_columns=bool(
                            raw.get("allow_across_columns", True)
                        ),
                    )
                )
            elif block_type == "reading":
                result.append(self._reading_block(raw, block_id))
        return result

    def _section_block(self, raw: dict[str, Any], block_id: str) -> RenderBlock:
        pieces: list[str] = []
        if raw.get("heading"):
            pieces.append(str(raw["heading"]))
        if raw.get("instruction"):
            pieces.append(str(raw["instruction"]))
        text = " ".join(pieces)
        style = ParagraphStyle(
            f"section-{block_id}",
            parent=self.section_style,
            # Ordinary question-range instructions are always flush left.
            # Reading headings retain their own alignment in _reading_block.
            alignment=TA_LEFT,
        )
        paragraph = Paragraph(f"<b>{to_reportlab_markup(text)}</b>", style)
        return RenderBlock(
            block_id=block_id,
            kind="section",
            flowables=[paragraph, Spacer(0, 5)],
            start_at_column_top=bool(raw.get("start_at_column_top", False)),
        )

    def _reading_block(self, raw: dict[str, Any], block_id: str) -> RenderBlock:
        flowables: list[Flowable] = []
        if raw.get("heading") or raw.get("instruction"):
            pieces = [
                str(piece)
                for piece in (raw.get("heading"), raw.get("instruction"))
                if piece
            ]
            style = ParagraphStyle(
                f"reading-heading-{block_id}",
                parent=self.section_style,
                alignment=(
                    TA_CENTER if raw.get("align", "center") == "center" else TA_LEFT
                ),
            )
            flowables.extend(
                [
                    Paragraph(
                        f"<b>{to_reportlab_markup(' '.join(pieces))}</b>", style
                    ),
                    Spacer(0, 5),
                ]
            )

        paragraphs = str(raw["passage"]).split("\n\n")
        for paragraph_index, paragraph_text in enumerate(paragraphs):
            if paragraph_text.strip():
                flowables.append(
                    Paragraph(to_reportlab_markup(paragraph_text.strip()), self.passage_style)
                )
                if paragraph_index < len(paragraphs) - 1:
                    flowables.append(Spacer(0, 4))
        flowables.append(Spacer(0, 6))
        for question_index, question in enumerate(raw["questions"]):
            question_flowables = self._question_flowables(question, include_gap=False)
            flowables.append(
                QuestionGroupFlowable(
                    question_flowables,
                    self.column_width,
                    self.page_height - self.top_margin - self.bottom_margin,
                )
            )
            if question_index < len(raw["questions"]) - 1:
                flowables.append(
                    Spacer(0, float(self.config["question_gap_pt"]))
                )
        flowables.append(Spacer(0, float(self.config["question_gap_pt"])))
        return RenderBlock(
            block_id=block_id,
            kind="reading",
            flowables=flowables,
            start_at_column_top=bool(raw.get("start_at_column_top", True)),
            allow_across_columns=True,
        )

    def _question_flowables(
        self, question: dict[str, Any], *, include_gap: bool
    ) -> list[Flowable]:
        number = str(question["number"])
        bullet = f"{number}."
        bullet_width = pdfmetrics.stringWidth(
            bullet, "ExamRoman", self.body_style.fontSize
        )
        question_style = ParagraphStyle(
            f"question-{number}",
            parent=self.body_style,
            leftIndent=bullet_width + 5,
            bulletIndent=0,
            firstLineIndent=0,
            bulletFontName="ExamRoman",
            bulletFontSize=self.body_style.fontSize,
        )
        stem = str(question["stem"])
        if "points" in question:
            stem += f"  [{question['points']}점]"
        flowables: list[Flowable] = [
            Paragraph(
                to_reportlab_markup(stem),
                question_style,
                bulletText=bullet,
            )
        ]

        if question.get("context"):
            flowables.extend([
                Spacer(0, 5),
                self._context_box(question["context"], bullet_width + 5),
            ])
        if question.get("segments"):
            for segment in question["segments"]:
                segment_style = ParagraphStyle(
                    f"segment-{number}-{segment['label']}",
                    parent=self.body_style,
                    leftIndent=bullet_width + 5 + 21,
                    bulletIndent=bullet_width + 5,
                    bulletFontName="ExamSymbols" if segment["label"][0] in "ⒶⒷⒸⒹⒺⒻⒼⒽⒾⒿⓀⓁⓂⓃⓄⓅⓆⓇⓈⓉⓊⓋⓌⓍⓎⓏ" else "ExamRoman",
                    bulletFontSize=self.body_style.fontSize,
                )
                flowables.extend([
                    Spacer(0, 5),
                    Paragraph(to_reportlab_markup(segment["text"]), segment_style,
                              bulletText=segment["label"]),
                ])

        options = question.get("options", []) if resolved_answer_format(question) != "inline" else []
        if options:
            flowables.append(
                Spacer(0, float(self.config["question_option_gap_pt"]))
            )
            columns = choose_option_columns(question)
            # Character counts are only a hint. Check actual font widths before
            # choosing two columns, especially for wide Latin letters and CJK.
            if columns == 2 and question.get("options_columns", "auto") == "auto":
                for index, option in enumerate(options):
                    paragraph = self._option_paragraph(option, index + 1, number,
                                                       option_base_indent=bullet_width + 5)
                    _, height = paragraph.wrap(self.column_width / 2 - 2, 100000)
                    if (height > self.body_style.leading + 0.01
                            or paragraph.minWidth() + paragraph.style.leftIndent > self.column_width / 2 - 2):
                        columns = 1
                        break
            option_paragraphs = [
                self._option_paragraph(
                    option,
                    index + 1,
                    number,
                    option_base_indent=bullet_width + 5,
                )
                for index, option in enumerate(options)
            ]
            if columns == 2:
                rows: list[list[Any]] = []
                for offset in range(0, len(option_paragraphs), 2):
                    left = option_paragraphs[offset]
                    right = (
                        option_paragraphs[offset + 1]
                        if offset + 1 < len(option_paragraphs)
                        else ""
                    )
                    rows.append([left, right])
                table = Table(
                    rows,
                    colWidths=[self.column_width / 2, self.column_width / 2],
                    hAlign="LEFT",
                )
                table.setStyle(
                    TableStyle(
                        [
                            ("LEFTPADDING", (0, 0), (-1, -1), 0),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                            ("TOPPADDING", (0, 0), (-1, -1), 0),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 0.4),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ]
                    )
                )
                flowables.append(table)
            else:
                for option_index, option_paragraph in enumerate(option_paragraphs):
                    flowables.append(option_paragraph)
                    if option_index < len(option_paragraphs) - 1:
                        flowables.append(Spacer(0, 0.8))

        if include_gap:
            flowables.append(Spacer(0, float(self.config["question_gap_pt"])))
        return flowables

    def _context_box(self, text: str, indent: float) -> Table:
        box = Table(
            [["", Paragraph(to_reportlab_markup(text), self.body_style)]],
            colWidths=[indent, self.column_width - indent],
            hAlign="LEFT",
        )
        box.setStyle(TableStyle([
            ("BOX", (1, 0), (1, -1), 0.45, colors.HexColor("#777777")),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return box

    def _option_paragraph(
        self,
        value: str,
        index: int,
        question_number: str,
        *,
        option_base_indent: float,
    ) -> Paragraph:
        marker = _choice_marker(index)
        marker_width = pdfmetrics.stringWidth(
            marker, "ExamSymbols", self.body_style.fontSize
        )
        style = ParagraphStyle(
            f"option-{question_number}-{index}",
            parent=self.body_style,
            # The complete choice begins where the question number ends.
            # Wrapped choice lines then align with the choice text, after ①.
            leftIndent=option_base_indent + marker_width + 4,
            bulletIndent=option_base_indent,
            firstLineIndent=0,
            # Times New Roman does not contain every circled numeral in all
            # Windows releases. The marker alone uses the Korean fallback;
            # option text remains Times New Roman.
            bulletFontName="ExamSymbols",
            bulletFontSize=self.body_style.fontSize,
        )
        return Paragraph(
            to_reportlab_markup(str(value)), style, bulletText=marker
        )

    def _place_block(self, block: RenderBlock) -> None:
        if block.start_at_column_top and not self._at_column_top():
            self._advance_column()

        height = self._measure(block.flowables)
        column_height = self._column_height()
        if height <= self._remaining_height():
            self._draw_whole_block(block)
            return

        if height <= column_height:
            self._advance_column()
            self._draw_whole_block(block)
            return

        if not block.allow_across_columns:
            raise LayoutError(
                f"{block.block_id} is taller than one column and is not allowed to span columns."
            )
        self._draw_across_columns(block)

    def _draw_whole_block(self, block: RenderBlock) -> None:
        start_page, start_column = self.page_number, self.column_index
        for flowable in block.flowables:
            width, height = flowable.wrap(self.column_width, self._remaining_height())
            flowable.drawOn(
                self.canvas,
                self.column_x[self.column_index],
                self.cursor_y - height,
            )
            self.cursor_y -= height
        self.placements.append(
            Placement(
                block.block_id,
                block.kind,
                start_page,
                start_column + 1,
                self.page_number,
                self.column_index + 1,
            )
        )

    def _draw_across_columns(self, block: RenderBlock) -> None:
        if not (self.column_index == 0 and self._at_column_top()):
            self._new_page()
        maximum = self._column_height() * 2
        height = self._measure(block.flowables)
        if height > maximum:
            raise LayoutError(
                f"{block.block_id} needs {height:.1f} pt, but one two-column page has "
                f"only {maximum:.1f} pt. Split the reading group or shorten it."
            )

        start_page = self.page_number
        queue: list[Flowable] = list(block.flowables)
        while queue:
            flowable = queue.pop(0)
            if isinstance(flowable, Spacer) and self._at_column_top():
                continue
            _, height = flowable.wrap(self.column_width, self._remaining_height())
            if height <= self._remaining_height() + 0.01:
                flowable.drawOn(
                    self.canvas,
                    self.column_x[self.column_index],
                    self.cursor_y - height,
                )
                self.cursor_y -= height
                continue

            remaining = self._remaining_height()
            parts = flowable.split(self.column_width, remaining)
            if parts and remaining >= self.body_style.leading:
                first, *rest = parts
                _, first_height = first.wrap(self.column_width, remaining)
                first.drawOn(
                    self.canvas,
                    self.column_x[self.column_index],
                    self.cursor_y - first_height,
                )
                self.cursor_y -= first_height
                queue = rest + queue
            else:
                # The item fits a fresh column but not the remaining space.
                # Keep it in the queue so advancing the column does not drop it.
                queue.insert(0, flowable)
            self._advance_column()
            if self.page_number != start_page:
                raise LayoutError(
                    f"{block.block_id} could not be kept on one page. Split the block."
                )

        self.placements.append(
            Placement(
                block.block_id,
                block.kind,
                start_page,
                1,
                self.page_number,
                self.column_index + 1,
            )
        )

    def _measure(self, flowables: Iterable[Flowable]) -> float:
        total = 0.0
        for flowable in flowables:
            _, height = flowable.wrap(self.column_width, 100000)
            total += height
        return total

    def _remaining_height(self) -> float:
        return self.cursor_y - self.bottom_margin

    def _column_height(self) -> float:
        return self.body_top - self.bottom_margin

    def _at_column_top(self) -> bool:
        return abs(self.cursor_y - self.body_top) < 0.1

    def _advance_column(self) -> None:
        if self.column_index == 0:
            self.column_index = 1
            self.cursor_y = self.body_top
        else:
            self._new_page()

    def _new_page(self) -> None:
        self.canvas.showPage()
        self._open_page()

    def _open_page(self) -> None:
        self.page_number += 1
        self.column_index = 0
        self.body_top = self.page_height - self.top_margin
        if self.page_number == 1 and self.document.get("show_header", True):
            self.body_top = self._draw_first_page_header()
        elif self.document.get("series_title") and (
            self.page_number == 1
            or self.document.get("series_title_every_page", True)
        ):
            self.body_top = self._draw_compact_series_header(self.body_top)
        self.cursor_y = self.body_top
        self._draw_page_decorations()

    def _draw_compact_series_header(self, top: float) -> float:
        """Draw a small running title without restoring the old exam-info box."""
        c = self.canvas
        title = str(self.document.get("series_title", "")).strip()
        c.saveState()
        c.setFont("ExamRoman-Bold", 10.5)
        c.drawString(self.left_margin, top - 8, title)
        c.setStrokeColor(colors.HexColor("#555555"))
        c.setLineWidth(0.45)
        c.line(
            self.left_margin,
            top - 14,
            self.page_width - self.right_margin,
            top - 14,
        )
        c.restoreState()
        return top - 24

    def _draw_first_page_header(self) -> float:
        c = self.canvas
        left = self.left_margin
        right = self.page_width - self.right_margin
        top = self.page_height - 11 * mm
        form_width, form_height = 34 * mm, 12 * mm
        c.setLineWidth(0.7)
        c.roundRect(right - form_width, top - form_height, form_width, form_height, 3 * mm)
        form = Paragraph(
            f"<b>{to_reportlab_markup(str(self.document.get('form', 'A')))}</b>",
            ParagraphStyle(
                "HeaderForm",
                parent=self.body_style,
                alignment=TA_CENTER,
                fontSize=16,
                leading=17,
            ),
        )
        _, form_h = form.wrap(form_width, form_height)
        form.drawOn(c, right - form_width, top - (form_height + form_h) / 2 + 1)

        box_top = top - 15 * mm
        candidate_table_height = 29 * mm if self.document.get("show_candidate_table", True) else 0
        box_height = 34 * mm + candidate_table_height
        box_bottom = box_top - box_height
        c.rect(left, box_bottom, right - left, box_height)

        title_style = ParagraphStyle(
            "HeaderTitle",
            parent=self.body_style,
            alignment=TA_CENTER,
            fontSize=15.5,
            leading=19,
        )
        title_text = to_reportlab_markup(str(self.document.get("title", "")))
        subtitle_text = to_reportlab_markup(str(self.document.get("subtitle", "")))
        title = Paragraph(f"{title_text}<br/><b>{subtitle_text}</b>", title_style)
        _, title_h = title.wrap(right - left - 20 * mm, 35 * mm)
        title.drawOn(c, left + 10 * mm, box_top - 4 * mm - title_h)

        info_y = box_top - 28 * mm
        info = (
            f"Subject: {self.document.get('subject', 'English')}    "
            f"Time: {self.document.get('duration_minutes', 60)} minutes"
        )
        info_p = Paragraph(
            to_reportlab_markup(info),
            ParagraphStyle("HeaderInfo", parent=self.body_style, fontSize=9, leading=11),
        )
        _, info_h = info_p.wrap(right - left - 10 * mm, 12 * mm)
        info_p.drawOn(c, left + 5 * mm, info_y - info_h)

        if self.document.get("show_candidate_table", True):
            table_data = [
                [
                    Paragraph(to_reportlab_markup("Department"), self._header_cell_style()),
                    Paragraph(to_reportlab_markup("Candidate No."), self._header_cell_style()),
                    Paragraph(to_reportlab_markup("Name"), self._header_cell_style()),
                ],
                ["", "", ""],
            ]
            table = Table(
                table_data,
                colWidths=[(right - left) / 3] * 3,
                rowHeights=[9 * mm, 19 * mm],
            )
            table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.45, colors.black),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f3f3")),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 2),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                        ("TOPPADDING", (0, 0), (-1, -1), 2),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ]
                )
            )
            _, table_h = table.wrap(right - left, candidate_table_height)
            table.drawOn(c, left, box_bottom + 0.5 * mm)

        return box_bottom - 5 * mm

    def _header_cell_style(self) -> ParagraphStyle:
        return ParagraphStyle(
            "HeaderCell",
            parent=self.body_style,
            alignment=TA_CENTER,
            fontSize=9.5,
            leading=11,
        )

    def _draw_page_decorations(self) -> None:
        c = self.canvas
        if self.config.get("column_rule", True):
            rule_x = self.left_margin + self.column_width + self.column_gap / 2
            c.saveState()
            c.setStrokeColor(colors.HexColor("#777777"))
            c.setLineWidth(0.35)
            c.line(rule_x, self.bottom_margin, rule_x, self.body_top)
            c.restoreState()

        first_page = int(self.document.get("first_page_number", 1))
        visible_page = first_page + self.page_number - 1
        code = str(self.document.get("exam_code", "ENG"))
        footer = f"[{code}] {visible_page}"
        c.saveState()
        c.setFont("ExamRoman", 9)
        c.drawCentredString(self.page_width / 2, 8 * mm, footer)
        c.restoreState()


def _choice_marker(index: int) -> str:
    circled = "①②③④⑤⑥⑦⑧⑨⑩"
    if 1 <= index <= len(circled):
        return circled[index - 1]
    return f"({index})"

