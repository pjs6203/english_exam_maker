from __future__ import annotations

import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .model import ExamInputError, normalize_exam
from .renderer import ExamRenderer, LayoutError


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXAMPLE = PROJECT_ROOT / "examples" / "sample_exam.json"


class ExamMakerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("English Exam Maker")
        self.root.geometry("1080x760")
        self.current_path: Path | None = None
        self.last_output: Path | None = None
        self.status = tk.StringVar(value="Ready")
        self.path_label = tk.StringVar(value="No file loaded")
        self._build_ui()
        if DEFAULT_EXAMPLE.exists():
            self._load_path(DEFAULT_EXAMPLE)

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self.root, padding=8)
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="Open JSON", command=self.open_json).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        ttk.Button(toolbar, text="Save", command=self.save_json).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(toolbar, text="Save As", command=self.save_json_as).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8
        )
        ttk.Button(toolbar, text="Validate", command=self.validate).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(toolbar, text="Generate PDF", command=self.generate).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(toolbar, text="Open Last PDF", command=self.open_last_pdf).pack(
            side=tk.LEFT, padx=5
        )

        ttk.Label(self.root, textvariable=self.path_label, padding=(10, 0)).pack(
            fill=tk.X
        )
        help_text = (
            "Inline markup: [[blank:6]] = 6-em blank, "
            "[[u]]word[[/u]] = underline, [[b]]text[[/b]] = bold, [[br]] = line break"
        )
        ttk.Label(self.root, text=help_text, padding=(10, 5)).pack(fill=tk.X)

        editor_frame = ttk.Frame(self.root, padding=(8, 0, 8, 5))
        editor_frame.pack(fill=tk.BOTH, expand=True)
        self.editor = tk.Text(
            editor_frame,
            wrap=tk.NONE,
            undo=True,
            font=("Consolas", 10),
            padx=10,
            pady=10,
        )
        y_scroll = ttk.Scrollbar(
            editor_frame, orient=tk.VERTICAL, command=self.editor.yview
        )
        x_scroll = ttk.Scrollbar(
            editor_frame, orient=tk.HORIZONTAL, command=self.editor.xview
        )
        self.editor.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.editor.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        editor_frame.rowconfigure(0, weight=1)
        editor_frame.columnconfigure(0, weight=1)

        ttk.Label(self.root, textvariable=self.status, relief=tk.SUNKEN, anchor=tk.W).pack(
            fill=tk.X, side=tk.BOTTOM
        )

    def _read_editor(self) -> dict:
        raw = self.editor.get("1.0", tk.END)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ExamInputError(
                f"JSON error at line {exc.lineno}, column {exc.colno}: {exc.msg}"
            ) from exc
        normalized, _ = normalize_exam(data)
        return normalized

    def _load_path(self, path: Path) -> None:
        content = path.read_text(encoding="utf-8-sig")
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", content)
        self.current_path = path
        self.path_label.set(str(path))
        self.status.set("Loaded")

    def open_json(self) -> None:
        selected = filedialog.askopenfilename(
            title="Open exam JSON",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if selected:
            try:
                self._load_path(Path(selected))
            except OSError as exc:
                messagebox.showerror("Open failed", str(exc))

    def save_json(self) -> bool:
        if self.current_path is None:
            return self.save_json_as()
        try:
            data = self._read_editor()
            self.current_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._load_path(self.current_path)
            self.status.set("Saved and formatted")
            return True
        except (ExamInputError, OSError) as exc:
            messagebox.showerror("Save failed", str(exc))
            return False

    def save_json_as(self) -> bool:
        selected = filedialog.asksaveasfilename(
            title="Save exam JSON",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if not selected:
            return False
        self.current_path = Path(selected)
        self.path_label.set(str(self.current_path))
        return self.save_json()

    def validate(self) -> None:
        try:
            raw = json.loads(self.editor.get("1.0", tk.END))
            _, warnings = normalize_exam(raw)
            detail = "Input is valid."
            if warnings:
                detail += "\n\nWarnings:\n- " + "\n- ".join(warnings)
            messagebox.showinfo("Validation", detail)
            self.status.set("Validation passed")
        except (json.JSONDecodeError, ExamInputError) as exc:
            messagebox.showerror("Validation failed", str(exc))
            self.status.set("Validation failed")

    def generate(self) -> None:
        try:
            data = self._read_editor()
        except ExamInputError as exc:
            messagebox.showerror("Cannot generate", str(exc))
            return

        initial_name = (
            f"{self.current_path.stem}.pdf" if self.current_path else "exam.pdf"
        )
        selected = filedialog.asksaveasfilename(
            title="Generate PDF",
            initialfile=initial_name,
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not selected:
            return
        try:
            self.status.set("Generating PDF...")
            self.root.update_idletasks()
            result = ExamRenderer(data).render(Path(selected))
            self.last_output = result.output_path
            detail = f"Created {result.page_count} page(s).\n{result.output_path}"
            if result.warnings:
                detail += "\n\nWarnings:\n- " + "\n- ".join(result.warnings)
            messagebox.showinfo("PDF generated", detail)
            self.status.set(f"Generated: {result.output_path}")
        except (LayoutError, ExamInputError, OSError, RuntimeError) as exc:
            messagebox.showerror("Generation failed", str(exc))
            self.status.set("Generation failed")

    def open_last_pdf(self) -> None:
        if not self.last_output or not self.last_output.exists():
            messagebox.showinfo("No PDF", "Generate a PDF first.")
            return
        if os.name == "nt":
            os.startfile(self.last_output)  # type: ignore[attr-defined]
        else:
            messagebox.showinfo("PDF path", str(self.last_output))


def launch_gui() -> None:
    root = tk.Tk()
    ExamMakerApp(root)
    root.mainloop()
