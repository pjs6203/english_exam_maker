from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


class FontError(RuntimeError):
    pass


@dataclass
class FontRegistration:
    roman_source: str
    korean_source: str
    warnings: list[str]


_REGISTERED = False
_REGISTRATION: FontRegistration | None = None


def register_exam_fonts() -> FontRegistration:
    global _REGISTERED, _REGISTRATION
    if _REGISTERED and _REGISTRATION is not None:
        return _REGISTRATION

    warnings: list[str] = []
    roman = _find_family(
        [
            (
                r"C:\Windows\Fonts\times.ttf",
                r"C:\Windows\Fonts\timesbd.ttf",
                r"C:\Windows\Fonts\timesi.ttf",
                r"C:\Windows\Fonts\timesbi.ttf",
                "Times New Roman",
            ),
            (
                "/Library/Fonts/Times New Roman.ttf",
                "/Library/Fonts/Times New Roman Bold.ttf",
                "/Library/Fonts/Times New Roman Italic.ttf",
                "/Library/Fonts/Times New Roman Bold Italic.ttf",
                "Times New Roman",
            ),
            (
                "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSerif-Italic.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSerif-BoldItalic.ttf",
                "Liberation Serif fallback",
            ),
        ]
    )
    if roman is None:
        raise FontError(
            "Times New Roman was not found. Install Microsoft core fonts or edit exam_maker/fonts.py."
        )
    if roman[4] != "Times New Roman":
        warnings.append("Times New Roman was unavailable; Liberation Serif was used.")

    korean = _find_family(
        [
            (
                r"C:\Windows\Fonts\malgun.ttf",
                r"C:\Windows\Fonts\malgunbd.ttf",
                r"C:\Windows\Fonts\malgun.ttf",
                r"C:\Windows\Fonts\malgunbd.ttf",
                "Malgun Gothic",
            ),
            (
                "/System/Library/Fonts/AppleSDGothicNeo.ttc",
                "/System/Library/Fonts/AppleSDGothicNeo.ttc",
                "/System/Library/Fonts/AppleSDGothicNeo.ttc",
                "/System/Library/Fonts/AppleSDGothicNeo.ttc",
                "Apple SD Gothic Neo",
            ),
            (
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                "Noto Sans CJK",
            ),
        ]
    )
    if korean is None:
        korean = roman
        warnings.append(
            "A Korean fallback font was not found; Korean glyphs may be missing."
        )

    _register_family("ExamRoman", roman)
    _register_family("ExamKorean", korean)
    _REGISTERED = True
    _REGISTRATION = FontRegistration(roman[4], korean[4], warnings)
    return _REGISTRATION


def _find_family(candidates: list[tuple[str, str, str, str, str]]):
    for candidate in candidates:
        if all(Path(path).exists() for path in candidate[:4]):
            return candidate
    return None


def _register_family(prefix: str, family: tuple[str, str, str, str, str]) -> None:
    normal, bold, italic, bold_italic, _ = family
    names = {
        prefix: normal,
        f"{prefix}-Bold": bold,
        f"{prefix}-Italic": italic,
        f"{prefix}-BoldItalic": bold_italic,
    }
    for name, path in names.items():
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, os.fspath(path)))
    pdfmetrics.registerFontFamily(
        prefix,
        normal=prefix,
        bold=f"{prefix}-Bold",
        italic=f"{prefix}-Italic",
        boldItalic=f"{prefix}-BoldItalic",
    )
