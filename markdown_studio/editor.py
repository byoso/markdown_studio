"""Simple Gtk.TextView based Markdown editor, no syntax highlighting yet."""
from __future__ import annotations

from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk as gtk, Pango


class MarkdownEditor(gtk.ScrolledWindow):
    def __init__(self):
        super().__init__()
        self.current_path: Path | None = None

        self.text_view = gtk.TextView()
        self.text_view.set_wrap_mode(gtk.WrapMode.WORD)
        self.text_view.set_left_margin(5)
        self.text_view.set_right_margin(5)
        self.text_view.set_top_margin(5)
        self.text_view.set_bottom_margin(5)
        self.set_font_size(15)
        self.buffer = self.text_view.get_buffer()
        self.add(self.text_view)

    def set_font_size(self, size: int) -> None:
        self.text_view.override_font(Pango.FontDescription(str(size)))

    def load_file(self, path: str | Path) -> None:
        self.current_path = Path(path)
        text = self.current_path.read_text(encoding="utf-8")
        self.buffer.set_text(text)

    def get_text(self) -> str:
        start, end = self.buffer.get_bounds()
        return self.buffer.get_text(start, end, True)

    def save(self) -> None:
        if self.current_path is None:
            return
        self.current_path.write_text(self.get_text(), encoding="utf-8")
