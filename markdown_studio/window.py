"""Main application window: file tree on the left, Markdown editor on the right."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk as gtk, Gdk, Gio, GLib

from silly_engine.logger import Logger

from . import pdf_export
from .editor import MarkdownEditor
from .file_tree import FileTree
from .html_preview import HTMLPreviewPane
from .markdown_renderer import render_body_html, render_html
from .preview import PreviewPane
from .project import Project, parse_order_prefix, set_order_prefix
from .settings import LOG_LEVEL


logger = Logger(__name__, level=LOG_LEVEL)


class MainWindow(gtk.Window):
    def __init__(self, project_path: str | Path, on_change_project=None):
        super().__init__(title="Markdown Studio")
        self.set_icon_from_file(str(Path(__file__).parent.parent / "icon.png"))
        self.set_default_size(900, 600)
        self.on_change_project = on_change_project
        self.project = Project.load(project_path)
        self._refreshing_file_tree = False

        self._load_app_css()
        self.set_titlebar(self._build_header_bar())

        paned = gtk.Paned(orientation=gtk.Orientation.HORIZONTAL)
        self.add(paned)

        left_box = gtk.Box(orientation=gtk.Orientation.VERTICAL)
        left_box.set_size_request(220, -1)
        paned.pack1(left_box, resize=False, shrink=False)

        sidebar_toolbar = gtk.Box(orientation=gtk.Orientation.HORIZONTAL, spacing=4)
        new_file_button = gtk.Button(label="New markdown file")
        new_file_button.get_style_context().add_class("sidebar-button")
        new_file_button.connect("clicked", self._on_new_file_clicked)
        sidebar_toolbar.pack_start(new_file_button, True, True, 0)

        refresh_button = gtk.Button()
        refresh_button.set_image(gtk.Image.new_from_icon_name("view-refresh-symbolic", gtk.IconSize.BUTTON))
        refresh_button.set_tooltip_text("Refresh")
        refresh_button.get_style_context().add_class("sidebar-button")
        refresh_button.connect("clicked", self._on_refresh_clicked)
        sidebar_toolbar.pack_start(refresh_button, False, False, 0)
        left_box.pack_start(sidebar_toolbar, False, False, 0)

        self.file_tree = FileTree(self.project.path)
        self.file_tree.connect("file-selected", self._on_file_selected)
        left_box.pack_start(self.file_tree, True, True, 0)

        right_box = gtk.Box(orientation=gtk.Orientation.VERTICAL)
        paned.pack2(right_box, resize=True, shrink=False)

        editor_toolbar = gtk.Box(orientation=gtk.Orientation.HORIZONTAL, spacing=4)
        save_button = gtk.Button(label="Save all")
        save_button.get_style_context().add_class("save-button")
        save_button.connect("clicked", self._on_save_all_clicked)
        export_file_button = gtk.Button(label="Export this file to PDF")
        export_file_button.get_style_context().add_class("export-button")
        export_file_button.connect("clicked", self._on_export_file_clicked)
        export_project_button = gtk.Button(label="Export project to PDF")
        export_project_button.get_style_context().add_class("export-button")
        export_project_button.connect("clicked", self._on_export_project_clicked)
        export_madoc_button = gtk.Button(label="Export HTML")
        export_madoc_button.get_style_context().add_class("export-button")
        export_madoc_button.connect("clicked", self._on_export_madoc_clicked)
        editor_toolbar.pack_start(save_button, False, False, 0)
        editor_toolbar.pack_start(export_file_button, False, False, 0)
        editor_toolbar.pack_start(export_project_button, False, False, 0)
        editor_toolbar.pack_start(export_madoc_button, False, False, 0)

        self.sync_toggle = gtk.ToggleButton(label="sync")
        self.sync_toggle.get_style_context().add_class("line-numbers-toggle")
        self.sync_toggle.set_tooltip_text("Sync editor/preview scroll position")
        editor_toolbar.pack_end(self.sync_toggle, False, False, 0)

        self.spellcheck_toggle = gtk.ToggleButton(label="orth")
        self.spellcheck_toggle.get_style_context().add_class("line-numbers-toggle")
        self.spellcheck_toggle.set_tooltip_text("Toggle spell checking")
        self.spellcheck_toggle.connect("toggled", self._on_toggle_spellcheck)
        editor_toolbar.pack_end(self.spellcheck_toggle, False, False, 0)

        self.line_numbers_toggle = gtk.ToggleButton(label="num")
        self.line_numbers_toggle.get_style_context().add_class("line-numbers-toggle")
        self.line_numbers_toggle.set_tooltip_text("Toggle line numbers")
        self.line_numbers_toggle.connect("toggled", self._on_toggle_line_numbers)
        editor_toolbar.pack_end(self.line_numbers_toggle, False, False, 0)

        self.preview_toggle = gtk.ToggleButton()
        self.preview_toggle.get_style_context().add_class("preview-toggle")
        self.preview_toggle.set_image(gtk.Image.new_from_icon_name("view-reveal-symbolic", gtk.IconSize.BUTTON))
        self.preview_toggle.set_tooltip_text("Toggle preview")
        self.preview_toggle.connect("toggled", self._on_toggle_preview)
        editor_toolbar.pack_end(self.preview_toggle, False, False, 0)

        right_box.pack_start(editor_toolbar, False, False, 0)

        content_paned = gtk.Paned(orientation=gtk.Orientation.HORIZONTAL)
        content_paned.set_position(450)
        right_box.pack_start(content_paned, True, True, 0)

        self.editor = MarkdownEditor()
        self.editor.text_view.get_style_context().add_class("markdown-editor")
        self.editor.set_font_size(self.project.get_font_size())
        self.editor.set_spellcheck_languages(self.project.get_spellcheck_languages())
        content_paned.pack1(self.editor, resize=True, shrink=False)

        self._last_markdown_path: Path | None = None

        preview_container = gtk.Box(orientation=gtk.Orientation.VERTICAL)
        preview_toolbar = gtk.Box(orientation=gtk.Orientation.HORIZONTAL, spacing=4)
        preview_toolbar.set_border_width(4)
        preview_toolbar.pack_start(gtk.Label(label="Preview:"), False, False, 0)
        self.render_preview_radio = gtk.RadioButton.new_with_label(None, "Render")
        self.html_preview_radio = gtk.RadioButton.new_with_label_from_widget(
            self.render_preview_radio, "html",
        )
        self.render_preview_radio.connect("toggled", self._on_preview_mode_changed)
        self.html_preview_radio.connect("toggled", self._on_preview_mode_changed)
        preview_toolbar.pack_start(self.render_preview_radio, False, False, 0)
        preview_toolbar.pack_start(self.html_preview_radio, False, False, 0)
        preview_container.pack_start(preview_toolbar, False, False, 0)

        self.preview_stack = gtk.Stack()
        self.preview = PreviewPane()
        self.html_preview = HTMLPreviewPane()
        self.preview_stack.add_named(self.preview, "render")
        self.preview_stack.add_named(self.html_preview, "html")
        preview_container.pack_start(self.preview_stack, True, True, 0)
        preview_container.set_size_request(300, -1)
        content_paned.pack2(preview_container, resize=True, shrink=False)

        self.editor.connect("buffer-changed", lambda _e: self._refresh_preview())
        self.editor.connect("modified-changed", self._on_editor_modified_changed)
        self.editor.connect("scrolled", self._on_editor_scrolled)
        self.preview.connect("scrolled", self._on_preview_scrolled)
        self.html_preview.connect("scrolled", self._on_preview_scrolled)
        self._last_synced_scroll_percent = 0.0

        self.preview_toggle.set_active(True)
        self.line_numbers_toggle.set_active(True)
        self.html_preview.set_show_line_numbers(True)
        self.sync_toggle.set_active(True)
        self.render_preview_radio.set_active(True)

        self.connect("key-press-event", self._on_key_press)

    def change_project(self, project_path: str | Path) -> None:
        self.project = Project.load(project_path)
        self.file_tree.set_root_path(self.project.path)
        self.editor.reset()
        self._last_markdown_path = None
        self.editor.set_font_size(self.project.get_font_size())
        self.editor.set_spellcheck_languages(self.project.get_spellcheck_languages())
        self.subtitle_label.set_text(self._header_subtitle())
        self._refresh_preview()

    def _on_editor_modified_changed(self, _editor, path: str, modified: bool) -> None:
        self.file_tree.set_modified(Path(path), modified)

    @staticmethod
    def _load_app_css() -> None:
        provider = gtk.CssProvider()
        provider.load_from_path(str(Path(__file__).parent / "style.css"))
        gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _build_header_bar(self) -> gtk.HeaderBar:
        self.header_bar = gtk.HeaderBar()
        self.header_bar.set_show_close_button(True)

        title_stack = gtk.Box(orientation=gtk.Orientation.VERTICAL, spacing=0)
        title_label = gtk.Label(label="Markdown Studio")
        title_label.get_style_context().add_class("title")
        self.subtitle_label = gtk.Label(label=self._header_subtitle())
        self.subtitle_label.get_style_context().add_class("subtitle")
        title_stack.pack_start(title_label, False, False, 0)
        title_stack.pack_start(self.subtitle_label, False, False, 0)

        title_box = gtk.Box(orientation=gtk.Orientation.HORIZONTAL, spacing=6)
        title_box.pack_start(title_stack, False, False, 0)

        self.save_indicator = gtk.Image.new_from_icon_name("emblem-ok-symbolic", gtk.IconSize.BUTTON)
        self.save_indicator.get_style_context().add_class("save-indicator")
        self.save_indicator.set_no_show_all(True)
        self.save_indicator.set_tooltip_text("Saved")
        title_box.pack_start(self.save_indicator, False, False, 0)

        title_box.show_all()
        self.save_indicator.hide()
        self.header_bar.set_custom_title(title_box)

        project_button = self._make_folder_button("Project")
        project_button.connect("clicked", lambda _b: self._open_folder(self.project.path))
        self.header_bar.pack_start(project_button)

        if self.on_change_project is not None:
            change_project_button = self._make_folder_button("Change project", "document-open-symbolic")
            change_project_button.connect("clicked", lambda _b: self.on_change_project())
            self.header_bar.pack_end(change_project_button)

        exports_button = self._make_folder_button("Exports")
        exports_button.connect("clicked", lambda _b: self._open_folder(self.project.get_exports_dir()))
        self.header_bar.pack_start(exports_button)

        settings_button = gtk.Button()
        settings_button.add(gtk.Image.new_from_icon_name("preferences-system-symbolic", gtk.IconSize.BUTTON))
        settings_button.set_tooltip_text("Project settings")
        settings_button.connect("clicked", self._on_settings_clicked)
        self.header_bar.pack_end(settings_button)

        return self.header_bar

    def _header_subtitle(self) -> str:
        return self.project.get_title() or self.project.path.name

    def _flash_save_indicator(self) -> None:
        self.save_indicator.show()
        GLib.timeout_add(1000, self._hide_save_indicator)

    def _hide_save_indicator(self) -> bool:
        self.save_indicator.hide()
        return False

    @staticmethod
    def _make_folder_button(label_text: str, icon_name: str = "folder-symbolic") -> gtk.Button:
        box = gtk.Box(orientation=gtk.Orientation.HORIZONTAL, spacing=4)
        box.pack_start(gtk.Image.new_from_icon_name(icon_name, gtk.IconSize.BUTTON), False, False, 0)
        box.pack_start(gtk.Label(label=label_text), False, False, 0)
        button = gtk.Button()
        button.add(box)
        return button

    @staticmethod
    def _open_folder(path: Path) -> None:
        Gio.AppInfo.launch_default_for_uri(f"file://{path}")

    def _on_file_selected(self, _widget, file_path: str) -> None:
        if self._refreshing_file_tree:
            return
        if self.editor.current_path is not None and str(self.editor.current_path) != file_path:
            logger.debug(f"{self.editor.current_path} - out - scroll: {self.editor.get_scroll_percent()}")
        self.editor.remember_current_scroll_position()
        # Rebuilding the file tree (e.g. on refresh) can re-fire this signal
        # for the file that is already open; reloading it would wipe undo history.
        if self.editor.current_path is not None and str(self.editor.current_path) == file_path:
            return
        if self.editor.load_file(file_path):
            self._refresh_preview()

    def _on_refresh_clicked(self, _button) -> None:
        logger.debug("refresh")
        self.editor.reload_files()
        self._refreshing_file_tree = True
        try:
            self.file_tree.refresh()
        finally:
            self._refreshing_file_tree = False
        self.editor.restore_current_scroll_position()
        self._refresh_preview()

    def _on_save_all_clicked(self, _button) -> None:
        self.editor.save_all()
        self._flash_save_indicator()

    def _on_toggle_preview(self, button: gtk.ToggleButton) -> None:
        if button.get_active():
            self.preview_stack.show()
            self._refresh_preview()
        else:
            self.preview_stack.hide()

    def _on_preview_mode_changed(self, button: gtk.RadioButton) -> None:
        if not button.get_active():
            return
        mode = "html" if button is self.html_preview_radio else "render"
        self.preview_stack.set_visible_child_name(mode)
        self._refresh_preview()

    def _on_toggle_line_numbers(self, button: gtk.ToggleButton) -> None:
        self.editor.set_show_line_numbers(button.get_active())
        self.html_preview.set_show_line_numbers(button.get_active())

    def _on_toggle_spellcheck(self, button: gtk.ToggleButton) -> None:
        self.editor.set_spellcheck_enabled(button.get_active())

    def _on_editor_scrolled(self, _editor) -> None:
        if not self.sync_toggle.get_active():
            return
        percent = self.editor.get_scroll_percent()
        # Ignore echoes of a sync we just applied, to avoid bouncing between editor and preview.
        if abs(percent - self._last_synced_scroll_percent) < 0.002:
            return
        self._last_synced_scroll_percent = percent
        if self.html_preview_radio.get_active():
            self.html_preview.set_scroll_percent(percent)
        else:
            self.preview.scroll_to_percent(percent)

    def _on_preview_scrolled(self, _preview, percent: float) -> None:
        if not self.sync_toggle.get_active():
            return
        if abs(percent - self._last_synced_scroll_percent) < 0.002:
            return
        self._last_synced_scroll_percent = percent
        self.editor.set_scroll_percent(percent)

    def _refresh_preview(self) -> None:
        if not self.preview_toggle.get_active():
            return
        current_path = self.editor.current_path
        if current_path is not None and current_path.suffix.lower() == ".md":
            is_new_file = self._last_markdown_path != current_path
            self._last_markdown_path = current_path
            markdown_text = self.editor.get_text()
            follow_bottom = self.editor.is_cursor_near_end()
        elif self._last_markdown_path is not None:
            try:
                markdown_text = self._last_markdown_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                # Stale reference (e.g. the file was renamed/reordered); drop it and skip this refresh.
                self._last_markdown_path = None
                return
            is_new_file = False
            follow_bottom = False
        else:
            return
        is_css_edit = current_path is not None and current_path.suffix.lower() == ".css"
        css_href = self.project.get_css_relative_path()
        body_html = render_body_html(markdown_text)
        if self.html_preview_radio.get_active():
            self.html_preview.set_html(
                render_html(markdown_text, css_href=css_href),
                reset_scroll=is_new_file,
            )
            return
        self.preview.refresh(
            css_href,
            self.project.path,
            body_html,
            reset_scroll=is_new_file,
            follow_bottom=follow_bottom,
            force_reload=is_css_edit,
        )

    def _on_key_press(self, _widget, event) -> bool:
        if event.keyval == Gdk.KEY_s and event.state & Gdk.ModifierType.CONTROL_MASK:
            self.editor.save()
            self._flash_save_indicator()
            return True
        if event.keyval == Gdk.KEY_z and event.state & Gdk.ModifierType.CONTROL_MASK:
            if self.editor.buffer.can_undo():
                self.editor.buffer.undo()
            return True
        if event.keyval == Gdk.KEY_y and event.state & Gdk.ModifierType.CONTROL_MASK:
            if self.editor.buffer.can_redo():
                self.editor.buffer.redo()
            return True
        if event.keyval == Gdk.KEY_f and event.state & Gdk.ModifierType.CONTROL_MASK:
            self.editor.focus_search()
            return True
        return False

    def _css_label_text(self) -> str:
        css_path = self.project.get_css_relative_path()
        return f"CSS: {css_path}" if css_path else "CSS: none"

    def _on_settings_clicked(self, _button) -> None:
        dialog = gtk.Dialog(title="Project settings", transient_for=self, flags=0)
        dialog.add_buttons(gtk.STOCK_CANCEL, gtk.ResponseType.CANCEL, gtk.STOCK_OK, gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_spacing(6)
        content.set_border_width(12)

        content.add(gtk.Label(label="Project title:", xalign=0))
        title_entry = gtk.Entry()
        title_entry.set_text(self.project.get_title() or "")
        content.add(title_entry)

        content.add(gtk.Label(label="Stylesheet:", xalign=0))
        preset_button = gtk.Button(label="Get a preset")
        preset_button.connect(
            "clicked",
            lambda _b: self._on_get_preset_clicked(dialog, css_label, remove_css_button),
        )
        content.add(preset_button)

        css_box = gtk.Box(orientation=gtk.Orientation.HORIZONTAL, spacing=4)
        css_label = gtk.Label(label=self._css_label_text())
        css_button = gtk.Button(label="Choose CSS file")
        remove_css_button = gtk.Button(label="Remove CSS file")
        remove_css_button.set_sensitive(self.project.get_css_relative_path() is not None)
        css_button.connect(
            "clicked",
            lambda _b: self._on_choose_css_clicked(dialog, css_label, remove_css_button),
        )
        remove_css_button.connect("clicked", lambda _b: self._on_remove_css_clicked(css_label, remove_css_button))
        css_box.pack_start(css_button, False, False, 0)
        css_box.pack_start(remove_css_button, False, False, 0)
        css_box.pack_start(css_label, False, False, 0)
        content.add(css_box)

        content.add(gtk.Label(label="Editor font size:", xalign=0))
        font_size_spin = gtk.SpinButton.new_with_range(6, 48, 1)
        font_size_spin.set_value(self.project.get_font_size())
        content.add(font_size_spin)

        content.add(gtk.Label(label="Spellcheck languages:", xalign=0))
        spellcheck_languages = self.project.get_spellcheck_languages()
        english_check = gtk.CheckButton(label="eng")
        english_check.set_active("en" in spellcheck_languages)
        french_check = gtk.CheckButton(label="fr")
        french_check.set_active("fr" in spellcheck_languages)
        content.add(english_check)
        content.add(french_check)

        dialog.show_all()
        response = dialog.run()
        if response == gtk.ResponseType.OK:
            self.project.set_title(title_entry.get_text().strip() or None)
            self.subtitle_label.set_text(self._header_subtitle())

            self.project.set_font_size(font_size_spin.get_value_as_int())
            self.editor.set_font_size(font_size_spin.get_value_as_int())

            selected_languages = []
            if english_check.get_active():
                selected_languages.append("en")
            if french_check.get_active():
                selected_languages.append("fr")
            self.project.set_spellcheck_languages(selected_languages)
            self.editor.set_spellcheck_languages(selected_languages)

            self._refresh_preview()
        dialog.destroy()

    def _on_choose_css_clicked(self, parent, css_label: gtk.Label, remove_css_button: gtk.Button) -> None:
        dialog = gtk.FileChooserDialog(
            title="Choose a CSS file", transient_for=parent, action=gtk.FileChooserAction.OPEN,
        )
        dialog.set_current_folder(str(self.project.path))
        dialog.add_buttons(gtk.STOCK_CANCEL, gtk.ResponseType.CANCEL, gtk.STOCK_OPEN, gtk.ResponseType.OK)
        css_filter = gtk.FileFilter()
        css_filter.set_name("CSS files")
        css_filter.add_pattern("*.css")
        dialog.add_filter(css_filter)
        response = dialog.run()
        css_path = dialog.get_filename()
        dialog.destroy()

        if response == gtk.ResponseType.OK and css_path:
            self.project.set_css_path(css_path)
            css_label.set_text(self._css_label_text())
            remove_css_button.set_sensitive(True)
            self._refresh_preview()

    def _on_remove_css_clicked(self, css_label: gtk.Label, remove_css_button: gtk.Button) -> None:
        self.project.set_css_path(None)
        css_label.set_text(self._css_label_text())
        remove_css_button.set_sensitive(False)
        self._refresh_preview()

    def _on_get_preset_clicked(self, parent, css_label: gtk.Label, remove_css_button: gtk.Button) -> None:
        presets_dir = Path(__file__).parent / "css_presets"
        dialog = gtk.FileChooserDialog(
            title="Choose a CSS preset", transient_for=parent, action=gtk.FileChooserAction.OPEN,
        )
        dialog.set_current_folder(str(presets_dir))
        dialog.add_buttons(gtk.STOCK_CANCEL, gtk.ResponseType.CANCEL, gtk.STOCK_OPEN, gtk.ResponseType.OK)
        css_filter = gtk.FileFilter()
        css_filter.set_name("CSS files")
        css_filter.add_pattern("*.css")
        dialog.add_filter(css_filter)
        response = dialog.run()
        preset_path = dialog.get_filename()
        dialog.destroy()

        if response != gtk.ResponseType.OK or not preset_path:
            return

        destination = self.project.path / Path(preset_path).name
        shutil.copy(preset_path, destination)
        self.project.set_css_path(destination)
        css_label.set_text(self._css_label_text())
        remove_css_button.set_sensitive(True)
        self.file_tree.refresh()
        self._refresh_preview()

    def _on_new_file_clicked(self, _button) -> None:
        dialog = gtk.Dialog(title="New markdown file", transient_for=self, flags=0)
        dialog.add_buttons(gtk.STOCK_CANCEL, gtk.ResponseType.CANCEL, gtk.STOCK_OK, gtk.ResponseType.OK)
        entry = gtk.Entry()
        entry.set_placeholder_text("File name (without extension)")
        dialog.get_content_area().add(entry)
        dialog.show_all()
        response = dialog.run()
        name = entry.get_text().strip()
        dialog.destroy()
        if response != gtk.ResponseType.OK or not name:
            return

        prefixes = [parse_order_prefix(p.name) for p in self.project.list_markdown_files()]
        prefixes = [p for p in prefixes if p is not None]
        next_prefix = max(prefixes) + 1 if prefixes else 1

        filename = set_order_prefix(f"{name}.md", next_prefix)
        (self.project.path / filename).write_text("", encoding="utf-8")
        self.file_tree.refresh()

    def _on_export_file_clicked(self, _button) -> None:
        if self.editor.current_path is None:
            return
        self.editor.save()

        pdf_path = self.project.get_exports_dir() / self.editor.current_path.with_suffix(".pdf").name
        pdf_export.export_single(self.project, self.editor.current_path, pdf_path)
        self._flash_save_indicator()

    def _on_export_project_clicked(self, _button) -> None:
        name = self._sanitize_filename(self.project.get_title() or self.project.path.name)
        pdf_path = self.project.get_exports_dir() / f"{name}.pdf"
        pdf_export.export_project(self.project, pdf_path)
        self._flash_save_indicator()

    def _on_export_madoc_clicked(self, _button) -> None:
        css_rel = self.project.get_css_relative_path()
        title = self.project.get_title() or self.project.path.name

        command = ["madoc"]
        if css_rel:
            command += ["--css", css_rel]
        command += ["-t", title]

        try:
            subprocess.run(command, cwd=self.project.path, check=True, capture_output=True, text=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as error:
            message = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
            self._show_error_dialog("Madoc export failed", message)
            return

        generated = self.project.path / "documentation.madoc.html"
        if generated.exists():
            generated.replace(self.project.get_exports_dir() / "index.html")
        self._flash_save_indicator()

    def _show_error_dialog(self, title: str, message: str) -> None:
        dialog = gtk.MessageDialog(
            transient_for=self, message_type=gtk.MessageType.ERROR,
            buttons=gtk.ButtonsType.OK, text=title,
        )
        dialog.format_secondary_text(message or "")
        dialog.run()
        dialog.destroy()

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "project"
