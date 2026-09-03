"""Gtk.TextView based editor with syntax highlighting via GtkSourceView."""
from __future__ import annotations

from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkSource", "4")
from gi.repository import Gtk as gtk, Gdk, GLib, GObject, GtkSource, Pango

from silly_engine.logger import Logger

from .settings import LOG_LEVEL
from .spellcheck import SpellCheckerEngine


logger = Logger(__name__, level=LOG_LEVEL)

# Map file extensions to GtkSourceView language ids.
_LANGUAGE_IDS = {
    ".md": "markdown",
    ".css": "css",
}

table_pattern = """
| title | title |
| --- | --- |
| 1 | 2 |
"""

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
        self.text_view.connect("button-press-event", self._on_text_view_button_press)
        self._set_tab_mode("4 spaces")
        self.set_font_size(15)

        self.pack_start(self._build_markdown_toolbar(), False, False, 0)

        self.scrolled_window = gtk.ScrolledWindow()
        self.scrolled_window.add(self.text_view)
        self.pack_start(self.scrolled_window, True, True, 0)
        self.scrolled_window.get_vadjustment().connect("value-changed", self._on_scroll_changed)
        self.text_view.connect("focus-out-event", self._on_editor_focus_out)

        self._scroll_positions: dict[str, float] = {}
        self._cursor_scroll_pending = False
        self._skip_cursor_scroll = False
        self._reloading_files = False
        self._restoring_scroll = False
        self._switching_buffer = False
        self._spellchecker = SpellCheckerEngine()
        self._spellcheck_enabled = False
        self._spellcheck_languages = ["en"]
        self._spellcheck_timer_id = 0
        # One GtkSource.Buffer per file, kept alive for the session so each file has
        # its own undo/redo history and unsaved edits survive switching files.
        self._buffers: dict[Path, GtkSource.Buffer] = {}

        self.search_settings = GtkSource.SearchSettings()
        self.search_settings.set_wrap_around(True)
        self.search_context = GtkSource.SearchContext.new(self.buffer, self.search_settings)
        self.search_context.set_highlight(True)
        self.search_context.connect("notify::occurrences-count", lambda *_a: self._update_match_count())

        self.pack_start(self._build_search_bar(), False, False, 0)

    def _build_markdown_toolbar(self) -> gtk.Box:
        toolbar = gtk.Box(orientation=gtk.Orientation.HORIZONTAL, spacing=4)
        toolbar.get_style_context().add_class("markdown-toolbar")

        page_break_button = gtk.Button(label="+break")
        page_break_button.set_tooltip_text("Insert a page break")
        page_break_button.connect("clicked", lambda _button: self.insert_page_break())
        toolbar.pack_start(page_break_button, False, False, 4)

        table_button = gtk.Button(label="+table")
        table_button.set_tooltip_text("Insert a Markdown table row")
        table_button.connect("clicked", lambda _button: self.insert_table_row())
        toolbar.pack_start(table_button, False, False, 0)

        return toolbar

    def insert_page_break(self) -> None:
        marker = "<!-- md:page-break -->"
        bounds = self.buffer.get_selection_bounds()
        if bounds:
            start, end = bounds
            self.buffer.delete(start, end)
            cursor = start
        else:
            cursor = self.buffer.get_iter_at_mark(self.buffer.get_insert())

        line_start = cursor.copy()
        line_start.set_line_offset(0)
        line_end = cursor.copy()
        line_end.forward_to_line_end()
        prefix = "" if cursor.equal(line_start) else "\n"
        suffix = "" if cursor.equal(line_end) else "\n"
        self.buffer.insert(cursor, f"{prefix}{marker}{suffix}")

    def insert_table_row(self) -> None:
        self.buffer.insert_at_cursor(table_pattern)

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

        search_bar.pack_start(gtk.Label(label="tab"), False, False, 4)
        self.tab_mode_button = gtk.MenuButton(label="4 spaces")
        self.tab_mode_button.set_tooltip_text("Choose what the Tab key inserts")
        tab_menu = gtk.Menu()
        for mode in ("4 spaces", "2 spaces", "tab"):
            item = gtk.MenuItem(label=mode)
            item.connect("activate", self._on_tab_mode_selected, mode)
            tab_menu.append(item)
        tab_menu.show_all()
        self.tab_mode_button.set_popup(tab_menu)
        search_bar.pack_start(self.tab_mode_button, False, False, 0)

        return search_bar

    def _on_tab_mode_selected(self, _item: gtk.MenuItem, mode: str) -> None:
        self.tab_mode_button.set_label(mode)
        self._set_tab_mode(mode)

    def _set_tab_mode(self, mode: str) -> None:
        if mode == "tab":
            self.text_view.set_tab_width(4)
            self.text_view.set_insert_spaces_instead_of_tabs(False)
            return
        self.text_view.set_tab_width(int(mode.split()[0]))
        self.text_view.set_insert_spaces_instead_of_tabs(True)

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
            self.text_view.scroll_to_iter(match_start, 0.2, False, 0, 0)
            GLib.idle_add(self._ensure_match_visible, match_start, match_end)
        self._update_match_count()

    def _ensure_match_visible(self, match_start, match_end) -> bool:
        visible_rect = self.text_view.get_visible_rect()
        start_rect = self.text_view.get_iter_location(match_start)
        end_rect = self.text_view.get_iter_location(match_end)
        margin = max(start_rect.height, end_rect.height) * 2
        if start_rect.y < visible_rect.y + margin:
            self.text_view.scroll_to_iter(match_start, 0.2, False, 0, 0)
        elif end_rect.y + end_rect.height > visible_rect.y + visible_rect.height - margin:
            self.text_view.scroll_to_iter(match_end, 0.2, False, 0, 0)
        return False

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
        self.text_view.set_bottom_margin(max(5, size * 3))

    def set_show_line_numbers(self, show: bool) -> None:
        self.text_view.set_show_line_numbers(show)

    def load_file(self, path: str | Path) -> bool:
        path = Path(path)
        if path not in self._buffers:
            try:
                text = path.read_text(encoding="utf-8")
            except (FileNotFoundError, UnicodeDecodeError):
                # Stale selection (e.g. the file was just renamed/reordered); ignore it.
                return False
            self._buffers[path] = self._create_buffer(path, text)
        self._remember_scroll_position()
        self.current_path = path
        self.buffer = self._buffers[path]
        logger.debug(f"{path} - in - scroll: {self._scroll_positions.get(str(path), 0)}")
        self._switching_buffer = True
        try:
            self.text_view.set_buffer(self.buffer)
        finally:
            self._switching_buffer = False
        # Each buffer needs its own search context since GtkSource.SearchContext is tied to one buffer.
        self.search_context = GtkSource.SearchContext.new(self.buffer, self.search_settings)
        self.search_context.set_highlight(True)
        self.search_context.connect("notify::occurrences-count", lambda *_a: self._update_match_count())
        self._search_from_start()
        self._schedule_spellcheck()
        self._restore_scroll_position(path)
        return True

    def reload_files(self) -> None:
        """Reload open files from disk, leaving unsaved buffers untouched."""
        current_path = self.current_path
        self._remember_scroll_position()
        self._skip_cursor_scroll = self._cursor_scroll_pending
        self._reloading_files = True
        try:
            for path, buffer in self._buffers.items():
                if buffer.get_modified() or not path.is_file():
                    continue
                buffer.begin_not_undoable_action()
                buffer.set_text(path.read_text(encoding="utf-8"))
                buffer.end_not_undoable_action()
                buffer.set_modified(False)
        finally:
            self._reloading_files = False

    def restore_current_scroll_position(self) -> None:
        """Restore the active file's saved scroll after the surrounding UI settles."""
        if self.current_path is not None:
            self._restore_scroll_position(self.current_path)

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
        self._ensure_spellcheck_tag(buffer)
        buffer.connect("changed", lambda changed_buffer: self._on_buffer_changed(changed_buffer))
        buffer.connect("modified-changed", lambda b: self.emit("modified-changed", str(path), b.get_modified()))
        return buffer

    def _on_buffer_changed(self, changed_buffer: GtkSource.Buffer) -> None:
        self.emit("buffer-changed")
        if changed_buffer is self.buffer:
            self._schedule_spellcheck()
        if not self._reloading_files and changed_buffer is self.buffer and self.text_view.is_focus():
            self._queue_cursor_scroll()

    def _queue_cursor_scroll(self) -> None:
        if self._cursor_scroll_pending:
            return
        self._cursor_scroll_pending = True
        GLib.idle_add(self._keep_cursor_spacing, self.buffer)

    def _keep_cursor_spacing(self, source_buffer: GtkSource.Buffer) -> bool:
        self._cursor_scroll_pending = False
        if self._skip_cursor_scroll or source_buffer is not self.buffer:
            self._skip_cursor_scroll = False
            return False
        cursor = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        cursor_rect = self.text_view.get_iter_location(cursor)
        visible_rect = self.text_view.get_visible_rect()
        line_height = max(1, cursor_rect.height)
        desired_bottom = visible_rect.y + visible_rect.height - (line_height * 3)
        cursor_bottom = cursor_rect.y + cursor_rect.height
        if cursor_bottom > desired_bottom:
            adjustment = self.scrolled_window.get_vadjustment()
            maximum = max(0, adjustment.get_upper() - adjustment.get_page_size())
            adjustment.set_value(min(maximum, adjustment.get_value() + cursor_bottom - desired_bottom))
        return False

    def is_cursor_near_end(self, lines: int = 2) -> bool:
        """Whether the caret sits within the last few lines, used to auto-follow the preview."""
        cursor_line = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_line()
        return cursor_line >= self.buffer.get_end_iter().get_line() - lines

    def _remember_scroll_position(self) -> None:
        if self.current_path is not None:
            percent = self.get_scroll_percent()
            self._scroll_positions[str(self.current_path)] = percent

    def _on_editor_focus_out(self, _text_view, _event) -> bool:
        self._remember_scroll_position()
        return False

    def _on_scroll_changed(self, _adjustment) -> None:
        if not self._reloading_files and not self._restoring_scroll and not self._switching_buffer:
            self._remember_scroll_position()
        self.emit("scrolled")

    def set_spellcheck_enabled(self, enabled: bool) -> None:
        self._spellcheck_enabled = enabled
        if enabled:
            self._schedule_spellcheck()
        else:
            self._clear_spellcheck_tags()

    def set_spellcheck_languages(self, languages: list[str]) -> None:
        self._spellcheck_languages = [language for language in ("en", "fr") if language in languages]
        if self._spellcheck_enabled:
            self._schedule_spellcheck()

    def _ensure_spellcheck_tag(self, buffer: GtkSource.Buffer) -> None:
        if buffer.get_tag_table().lookup("spell-error") is None:
            buffer.create_tag(
                "spell-error",
                underline=Pango.Underline.ERROR,
                foreground="#c45a5a",
            )

    def _clear_spellcheck_tags(self) -> None:
        tag = self.buffer.get_tag_table().lookup("spell-error")
        if tag is not None:
            self.buffer.remove_tag(tag, self.buffer.get_start_iter(), self.buffer.get_end_iter())

    def _schedule_spellcheck(self) -> None:
        if self._spellcheck_timer_id:
            GLib.source_remove(self._spellcheck_timer_id)
        self._spellcheck_timer_id = GLib.timeout_add(250, self._run_spellcheck)

    def _run_spellcheck(self) -> bool:
        self._spellcheck_timer_id = 0
        if not self._spellcheck_enabled:
            return False
        self._ensure_spellcheck_tag(self.buffer)
        self._clear_spellcheck_tags()
        start, end = self.buffer.get_bounds()
        text = self.buffer.get_text(start, end, True)
        for word_start, word_end in self._spellchecker.misspelled_spans(text, self._spellcheck_languages):
            self.buffer.apply_tag(
                self.buffer.get_tag_table().lookup("spell-error"),
                self.buffer.get_iter_at_offset(word_start),
                self.buffer.get_iter_at_offset(word_end),
            )
        return False

    def _on_text_view_button_press(self, _text_view, event) -> bool:
        if event.button != 3 or not self._spellcheck_enabled:
            return False
        window_x, window_y = self.text_view.window_to_buffer_coords(
            gtk.TextWindowType.WIDGET, int(event.x), int(event.y),
        )
        found, clicked_iter = self.text_view.get_iter_at_location(window_x, window_y)
        if not found:
            return False
        tag = self.buffer.get_tag_table().lookup("spell-error")
        if tag is None or not clicked_iter.has_tag(tag):
            return False

        word_start = clicked_iter.copy()
        word_end = clicked_iter.copy()
        word_start.backward_word_start()
        word_end.forward_word_end()
        word = self.buffer.get_text(word_start, word_end, True)
        self.buffer.select_range(word_start, word_end)
        suggestions = self._spellchecker.suggestions(word, self._spellcheck_languages)
        if not suggestions:
            return False

        menu = gtk.Menu()
        for suggestion in suggestions:
            item = gtk.MenuItem(label=suggestion)
            item.connect(
                "activate", self._replace_spelling, word_start.get_offset(),
                word_end.get_offset(), suggestion,
            )
            menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    def _replace_spelling(self, _item, start_offset: int, end_offset: int, replacement: str) -> None:
        start = self.buffer.get_iter_at_offset(start_offset)
        end = self.buffer.get_iter_at_offset(end_offset)
        self.buffer.begin_user_action()
        self.buffer.delete(start, end)
        self.buffer.insert(self.buffer.get_iter_at_offset(start_offset), replacement)
        self.buffer.end_user_action()

    def remember_current_scroll_position(self) -> None:
        self._remember_scroll_position()

    def _restore_scroll_position(self, path: Path) -> None:
        percent = self._scroll_positions.get(str(path), 0)
        attempts = 0

        def apply_scroll() -> bool:
            nonlocal attempts
            if self.current_path != path:
                return False
            attempts += 1
            adjustment = self.scrolled_window.get_vadjustment()
            maximum = max(0.0, adjustment.get_upper() - adjustment.get_page_size())
            if percent > 0 and maximum <= 0 and attempts < 20:
                return True
            self._restoring_scroll = True
            try:
                self.set_scroll_percent(percent)
            finally:
                self._restoring_scroll = False
            return attempts < 4

        # Deferred: the buffer's new content must be laid out before the
        # adjustment's range reflects the new document's height.
        GLib.timeout_add(25, apply_scroll)

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
        self._ensure_spellcheck_tag(self.buffer)
        self._schedule_spellcheck()
        self.search_context = GtkSource.SearchContext.new(self.buffer, self.search_settings)
        self.search_context.set_highlight(True)
        self.search_context.connect("notify::occurrences-count", lambda *_a: self._update_match_count())
