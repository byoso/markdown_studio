"""Read-only, syntax-highlighted view of the generated HTML document."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "4")
from gi.repository import Gtk as gtk, GObject, GtkSource


class HTMLPreviewPane(gtk.Box):
    """Display generated HTML as selectable, non-editable source code."""

    __gsignals__ = {
        "scrolled": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
    }

    def __init__(self):
        super().__init__(orientation=gtk.Orientation.VERTICAL)
        self.buffer = GtkSource.Buffer()
        self.buffer.set_highlight_syntax(True)
        language_manager = GtkSource.LanguageManager.get_default()
        language = language_manager.get_language("html")
        if language is not None:
            self.buffer.set_language(language)
        style_scheme = GtkSource.StyleSchemeManager.get_default().get_scheme("solarized-dark")
        if style_scheme is not None:
            self.buffer.set_style_scheme(style_scheme)

        self.text_view = GtkSource.View.new_with_buffer(self.buffer)
        self.text_view.set_editable(False)
        self.text_view.set_cursor_visible(False)
        self.text_view.set_wrap_mode(gtk.WrapMode.NONE)
        self.text_view.set_monospace(True)
        self.text_view.set_left_margin(8)
        self.text_view.set_right_margin(8)
        self.text_view.set_top_margin(8)
        self.text_view.set_bottom_margin(8)

        self.scrolled_window = gtk.ScrolledWindow()
        self.scrolled_window.add(self.text_view)
        self.pack_start(self.scrolled_window, True, True, 0)
        self.scrolled_window.get_vadjustment().connect(
            "value-changed", self._on_scroll_changed,
        )

    def set_html(self, html_text: str, reset_scroll: bool = False) -> None:
        adjustment = self.scrolled_window.get_vadjustment()
        scroll_value = adjustment.get_value()
        self.buffer.set_text(html_text)
        if reset_scroll:
            adjustment.set_value(0)
        else:
            adjustment.set_value(scroll_value)

    def set_show_line_numbers(self, show: bool) -> None:
        self.text_view.set_show_line_numbers(show)

    def _on_scroll_changed(self, _adjustment) -> None:
        self.emit("scrolled", self.get_scroll_percent())

    def get_scroll_percent(self) -> float:
        adjustment = self.scrolled_window.get_vadjustment()
        maximum = max(1.0, adjustment.get_upper() - adjustment.get_page_size())
        return min(1.0, max(0.0, adjustment.get_value() / maximum))

    def set_scroll_percent(self, percent: float) -> None:
        adjustment = self.scrolled_window.get_vadjustment()
        maximum = max(0.0, adjustment.get_upper() - adjustment.get_page_size())
        adjustment.set_value(percent * maximum)
