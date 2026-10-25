from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .model import ExamInputError, load_exam
from .renderer import ExamRenderer, LayoutError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="english-exam-maker",
        description="Generate a two-column English exam paper from JSON.",
    )
    subparsers = parser.add_subparsers(dest="command")

    render_parser = subparsers.add_parser("render", help="Render JSON to PDF")
    render_parser.add_argument("input", type=Path)
    render_parser.add_argument("-o", "--output", type=Path, required=True)
    render_parser.add_argument(
        "--manifest", type=Path, help="Optional layout diagnostic JSON"
    )

    validate_parser = subparsers.add_parser("validate", help="Validate exam JSON")
    validate_parser.add_argument("input", type=Path)

    subparsers.add_parser("gui", help="Open the desktop editor")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "gui"
    if command == "gui":
        from .gui import launch_gui

        launch_gui()
        return 0

    try:
        data, warnings = load_exam(args.input)
        if command == "validate":
            print(f"Valid: {args.input}")
            for warning in warnings:
                print(f"Warning: {warning}")
            return 0

        renderer = ExamRenderer(data)
        result = renderer.render(args.output, layout_manifest_path=args.manifest)
        print(f"Created: {result.output_path}")
        print(f"Pages: {result.page_count}")
        for warning in dict.fromkeys(warnings + result.warnings):
            print(f"Warning: {warning}")
        return 0
    except (ExamInputError, LayoutError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

