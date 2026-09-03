from __future__ import annotations

import html
import re

from .model import ExamInputError


TOKEN_RE = re.compile(r"\[\[([^\]]+)\]\]")
CJK_RE = re.compile(r"([\u1100-\u11ff\u3130-\u318f\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]+)")


def to_reportlab_markup(value: str) -> str:
    """Convert the small exam markup language to ReportLab Paragraph markup."""
    output: list[str] = []
    cursor = 0
    stack: list[str] = []

    for match in TOKEN_RE.finditer(value):
        output.append(_plain_text(value[cursor : match.start()]))
        token = match.group(1).strip()
        if token.startswith("blank"):
            if token == "blank":
                em_width = 5.0
            else:
                pieces = token.split(":", 1)
                if len(pieces) != 2:
                    raise ExamInputError(f"Invalid blank token: [[{token}]]")
                try:
                    em_width = float(pieces[1])
                except ValueError as exc:
                    raise ExamInputError(
                        f"Blank width must be numeric: [[{token}]]"
                    ) from exc
            if not 1.0 <= em_width <= 20.0:
                raise ExamInputError("Blank width must be between 1 and 20 em.")
            spaces = "&#160;" * max(4, round(em_width * 4))
            output.append(f'<u width="0.7">{spaces}</u>')
        elif token in {"u", "b", "i"}:
            stack.append(token)
            output.append(f"<{token}>")
        elif token in {"/u", "/b", "/i"}:
            closing = token[1:]
            if not stack or stack[-1] != closing:
                raise ExamInputError(f"Unbalanced markup token: [[{token}]]")
            stack.pop()
            output.append(f"</{closing}>")
        elif token == "br":
            output.append("<br/>")
        else:
            raise ExamInputError(f"Unsupported markup token: [[{token}]]")
        cursor = match.end()

    output.append(_plain_text(value[cursor:]))
    if stack:
        raise ExamInputError(f"Unclosed markup token: [[{stack[-1]}]]")
    return "".join(output)


def _plain_text(value: str) -> str:
    if not value:
        return ""
    pieces: list[str] = []
    for part in CJK_RE.split(value):
        if not part:
            continue
        escaped = html.escape(part).replace("\n", "<br/>")
        if CJK_RE.fullmatch(part):
            pieces.append(f'<font name="ExamKorean">{escaped}</font>')
        else:
            pieces.append(escaped)
    return "".join(pieces)
