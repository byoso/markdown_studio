"""Live HTML preview of the Markdown being edited, rendered via WebKit2Gtk."""
from __future__ import annotations

from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk as gtk, WebKit2


class PreviewPane(gtk.Box):
    def __init__(self):
        super().__init__(orientation=gtk.Orientation.VERTICAL)
        self.web_view = WebKit2.WebView()
        self.pack_start(self.web_view, True, True, 0)

    def load_html(self, html: str, base_path: str | Path) -> None:
        self.web_view.load_html(html, f"file://{base_path}/")
