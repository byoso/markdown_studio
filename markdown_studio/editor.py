"""Gtk.TextView based editor with syntax highlighting via GtkSourceView."""
from __future__ import annotations

from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "4")
from gi.repository import Gtk as gtk, Gdk, GLib, GObject, GtkSource, Pango

# Map file extensions to GtkSourceView language ids.
_LANGUAGE_IDS = {
    ".md": "markdown",
    ".css": "css",
}


class MarkdownEditor(gtk.Box):
    __gsignals__ = {
        # Fired whenever the visible buffer's text changes (used to refresh the preview).
        "buffer-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # Fired whenever a file's unsaved-changes state changes: (path str, is_modified bool).
        "modified-changed": (GObject.SignalFlags.RUN_FIRST, None, (str, bool)),
        # Fired whenever the editor is scrolled (used to sync the preview's scroll position).
        "scrolled": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(orientation=gtk.Orientation.VERTICAL)
        self.current_path: Path | None = None
        self._language_manager = GtkSource.LanguageManager.get_default()
        self._style_scheme = GtkSource.StyleSchemeManager.get_default().get_scheme("solarized-dark")

        # Placeholder buffer shown before any file is opened.
        self.buffer = GtkSource.Buffer()
        self.buffer.set_highlight_syntax(True)
        if self._style_scheme is not None:
            self.buffer.set_style_scheme(self._style_scheme)

        self.text_view = GtkSource.View.new_with_buffer(self.buffer)
        self.text_view.set_wrap_mode(gtk.WrapMode.WORD)
        self.text_view.set_left_margin(5)
        self.text_view.set_right_margin(5)
        self.text_view.set_top_margin(5)
        self.text_view.set_bottom_margin(5)
        self.set_font_size(15)

        self.scrolled_window = gtk.ScrolledWindow()
        self.scrolled_window.add(self.text_view)
        self.pack_start(self.scrolled_window, True, True, 0)
        self.scrolled_window.get_vadjustment().connect("value-changed", lambda _a: self.emit("scrolled"))

        self._scroll_positions: dict[Path, float] = {}
        # One GtkSource.Buffer per file, kept alive for the session so each file has
        # its own undo/redo history and unsaved edits survive switching files.
        self._buffers: dict[Path, GtkSource.Buffer] = {}

        self.search_settings = GtkSource.SearchSettings()
        self.search_settings.set_wrap_around(True)
        self.search_context = GtkSource.SearchContext.new(self.buffer, self.search_settings)
        self.search_context.set_highlight(True)
        self.search_context.connect("notify::occurrences-count", lambda *_a: self._update_match_count())

        self.pack_start(self._build_search_bar(), False, False, 0)

    def _build_search_bar(self) -> gtk.Box:
        search_bar = gtk.Box(orientation=gtk.Orientation.HORIZONTAL, spacing=4)
        search_bar.get_style_context().add_class("search-bar")

        search_bar.pack_start(gtk.Image.new_from_icon_name("edit-find-symbolic", gtk.IconSize.BUTTON), False, False, 4)

        self.search_entry = gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Find in file\u2026")
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("activate", lambda _e: self._search_next())
        self.search_entry.connect("key-press-event", self._on_search_key_press)
        search_bar.pack_start(self.search_entry, True, True, 0)

        self.match_count_label = gtk.Label(label="")
        self.match_count_label.get_style_context().add_class("dim-label")
        search_bar.pack_start(self.match_count_label, False, False, 4)

        previous_button = gtk.Button()
        previous_button.set_image(gtk.Image.new_from_icon_name("go-up-symbolic", gtk.IconSize.BUTTON))
        previous_button.set_tooltip_text("Previous match")
        previous_button.connect("clicked", lambda _b: self._search_previous())
        search_bar.pack_start(previous_button, False, False, 0)

        next_button = gtk.Button()
        next_button.set_image(gtk.Image.new_from_icon_name("go-down-symbolic", gtk.IconSize.BUTTON))
        next_button.set_tooltip_text("Next match")
        next_button.connect("clicked", lambda _b: self._search_next())
        search_bar.pack_start(next_button, False, False, 0)

        return search_bar

    def _on_search_key_press(self, _entry, event) -> bool:
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and event.state & Gdk.ModifierType.SHIFT_MASK:
            self._search_previous()
            return True
        return False

    def _on_search_changed(self, entry: gtk.SearchEntry) -> None:
        text = entry.get_text()
        self.search_settings.set_search_text(text or None)
        if not text:
            self._update_match_count()
            return
        bounds = self.buffer.get_selection_bounds()
        anchor = bounds[0] if bounds else self.buffer.get_iter_at_mark(self.buffer.get_insert())
        self._select_match(*self.search_context.forward(anchor)[:3])

    def _search_next(self) -> None:
        if not self.search_settings.get_search_text():
            return
        bounds = self.buffer.get_selection_bounds()
        anchor = bounds[1] if bounds else self.buffer.get_iter_at_mark(self.buffer.get_insert())
        self._select_match(*self.search_context.forward(anchor)[:3])

    def _search_previous(self) -> None:
        if not self.search_settings.get_search_text():
            return
        bounds = self.buffer.get_selection_bounds()
        anchor = bounds[0] if bounds else self.buffer.get_iter_at_mark(self.buffer.get_insert())
        self._select_match(*self.search_context.backward(anchor)[:3])

    def _select_match(self, found: bool, match_start, match_end) -> None:
        if found:
            self.buffer.select_range(match_start, match_end)
            self.text_view.scroll_to_iter(match_start, 0.1, False, 0, 0)
        self._update_match_count()

    def _search_from_start(self) -> None:
        """Re-apply the active search to the buffer's current content, e.g. after loading a new file."""
        if not self.search_settings.get_search_text():
            self._update_match_count()
            return
        self._select_match(*self.search_context.forward(self.buffer.get_start_iter())[:3])

    def _update_match_count(self) -> None:
        if not self.search_settings.get_search_text():
            self.match_count_label.set_text("")
            return
        total = self.search_context.get_occurrences_count()
        bounds = self.buffer.get_selection_bounds()
        if total <= 0 or not bounds:
            self.match_count_label.set_text("0/0")
            return
        position = self.search_context.get_occurrence_position(bounds[0], bounds[1])
        self.match_count_label.set_text(f"{position}/{total}" if position > 0 else f"?/{total}")

    def focus_search(self) -> None:
        self.search_entry.grab_focus()

    def set_font_size(self, size: int) -> None:
        self.text_view.override_font(Pango.FontDescription(str(size)))

    def set_show_line_numbers(self, show: bool) -> None:
        self.text_view.set_show_line_numbers(show)

    def load_file(self, path: str | Path) -> bool:
        path = Path(path)
        if path not in self._buffers:
            try:
                text = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                # Stale selection (e.g. the file was just renamed/reordered); ignore it.
                return False
            self._buffers[path] = self._create_buffer(path, text)
        self._remember_scroll_position()
        self.current_path = path
        self.buffer = self._buffers[path]
        self.text_view.set_buffer(self.buffer)
        # Each buffer needs its own search context since GtkSource.SearchContext is tied to one buffer.
        self.search_context = GtkSource.SearchContext.new(self.buffer, self.search_settings)
        self.search_context.set_highlight(True)
        self.search_context.connect("notify::occurrences-count", lambda *_a: self._update_match_count())
        self._search_from_start()
        self._restore_scroll_position(path)
        return True

    def _create_buffer(self, path: Path, text: str) -> GtkSource.Buffer:
        buffer = GtkSource.Buffer()
        buffer.set_highlight_syntax(True)
        if self._style_scheme is not None:
            buffer.set_style_scheme(self._style_scheme)
        buffer.set_language(self._guess_language(path))
        # Loading the initial content must not be undoable.
        buffer.begin_not_undoable_action()
        buffer.set_text(text)
        buffer.end_not_undoable_action()
        buffer.set_modified(False)
        buffer.connect("changed", lambda _b: self.emit("buffer-changed"))
        buffer.connect("modified-changed", lambda b: self.emit("modified-changed", str(path), b.get_modified()))
        return buffer

    def is_cursor_near_end(self, lines: int = 2) -> bool:
        """Whether the caret sits within the last few lines, used to auto-follow the preview."""
        cursor_line = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_line()
        return cursor_line >= self.buffer.get_end_iter().get_line() - lines

    def _remember_scroll_position(self) -> None:
        if self.current_path is not None:
            self._scroll_positions[self.current_path] = self.scrolled_window.get_vadjustment().get_value()

    def _restore_scroll_position(self, path: Path) -> None:
        value = self._scroll_positions.get(path, 0)

        def apply_scroll() -> bool:
            adjustment = self.scrolled_window.get_vadjustment()
            upper = max(0, adjustment.get_upper() - adjustment.get_page_size())
            adjustment.set_value(min(value, upper))
            return False

        # Deferred: the buffer's new content must be laid out before the
        # adjustment's range reflects the new document's height.
        GLib.idle_add(apply_scroll)

    def _guess_language(self, path: Path) -> GtkSource.Language | None:
        language_id = _LANGUAGE_IDS.get(path.suffix.lower())
        return self._language_manager.get_language(language_id) if language_id else None

    def get_scroll_percent(self) -> float:
        adjustment = self.scrolled_window.get_vadjustment()
        max_value = max(1.0, adjustment.get_upper() - adjustment.get_page_size())
        return min(1.0, max(0.0, adjustment.get_value() / max_value))

    def set_scroll_percent(self, percent: float) -> None:
        adjustment = self.scrolled_window.get_vadjustment()
        max_value = max(0.0, adjustment.get_upper() - adjustment.get_page_size())
        adjustment.set_value(percent * max_value)

    def get_text(self) -> str:
        start, end = self.buffer.get_bounds()
        return self.buffer.get_text(start, end, True)

    def save(self) -> None:
        if self.current_path is None:
            return
        self.current_path.write_text(self.get_text(), encoding="utf-8")
        self.buffer.set_modified(False)

    def save_all(self) -> None:
        for path, buffer in self._buffers.items():
            if not buffer.get_modified():
                continue
            start, end = buffer.get_bounds()
            path.write_text(buffer.get_text(start, end, True), encoding="utf-8")
            buffer.set_modified(False)

    def reset(self) -> None:
        """Discard all open files' buffers, e.g. when switching to a different project."""
        self.current_path = None
        self._buffers.clear()
        self._scroll_positions.clear()
        self.buffer = GtkSource.Buffer()
        self.buffer.set_highlight_syntax(True)
        if self._style_scheme is not None:
            self.buffer.set_style_scheme(self._style_scheme)
        self.text_view.set_buffer(self.buffer)
        self.search_context = GtkSource.SearchContext.new(self.buffer, self.search_settings)
        self.search_context.set_highlight(True)
        self.search_context.connect("notify::occurrences-count", lambda *_a: self._update_match_count())
