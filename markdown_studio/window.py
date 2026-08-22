"""Main application window: file tree on the left, Markdown editor on the right."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk as gtk, Gdk, Gio, GLib

from . import pdf_export
from .editor import MarkdownEditor
from .file_tree import FileTree
from .markdown_renderer import render_html
from .preview import PreviewPane
from .project import Project, parse_order_prefix, set_order_prefix


class MainWindow(gtk.Window):
    def __init__(self, project_path: str | Path):
        super().__init__(title="Markdown Studio")
        self.set_default_size(900, 600)
        self.project = Project.load(project_path)

        self._load_app_css()
        self.set_titlebar(self._build_header_bar())

        paned = gtk.Paned(orientation=gtk.Orientation.HORIZONTAL)
        self.add(paned)

        left_box = gtk.Box(orientation=gtk.Orientation.VERTICAL)
        left_box.set_size_request(220, -1)
        paned.pack1(left_box, resize=False, shrink=False)

        new_file_button = gtk.Button(label="New markdown file")
        new_file_button.get_style_context().add_class("sidebar-button")
        new_file_button.connect("clicked", self._on_new_file_clicked)
        left_box.pack_start(new_file_button, False, False, 0)

        self.file_tree = FileTree(self.project.path)
        self.file_tree.connect("file-selected", self._on_file_selected)
        left_box.pack_start(self.file_tree, True, True, 0)

        right_box = gtk.Box(orientation=gtk.Orientation.VERTICAL)
        paned.pack2(right_box, resize=True, shrink=False)

        editor_toolbar = gtk.Box(orientation=gtk.Orientation.HORIZONTAL, spacing=4)
        save_button = gtk.Button(label="Save")
        save_button.get_style_context().add_class("save-button")
        save_button.connect("clicked", self._on_save_clicked)
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
        content_paned.pack1(self.editor, resize=True, shrink=False)

        self.preview = PreviewPane()
        self.preview.set_size_request(300, -1)
        content_paned.pack2(self.preview, resize=True, shrink=False)

        self.editor.buffer.connect("changed", lambda _b: self._refresh_preview())

        self.preview_toggle.set_active(True)

        self.connect("key-press-event", self._on_key_press)

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
    def _make_folder_button(label_text: str) -> gtk.Button:
        box = gtk.Box(orientation=gtk.Orientation.HORIZONTAL, spacing=4)
        box.pack_start(gtk.Image.new_from_icon_name("folder-symbolic", gtk.IconSize.BUTTON), False, False, 0)
        box.pack_start(gtk.Label(label=label_text), False, False, 0)
        button = gtk.Button()
        button.add(box)
        return button

    @staticmethod
    def _open_folder(path: Path) -> None:
        Gio.AppInfo.launch_default_for_uri(f"file://{path}")

    def _on_file_selected(self, _widget, file_path: str) -> None:
        if file_path.endswith(".md"):
            self.editor.load_file(file_path)

    def _on_save_clicked(self, _button) -> None:
        self.editor.save()
        self._flash_save_indicator()

    def _on_toggle_preview(self, button: gtk.ToggleButton) -> None:
        if button.get_active():
            self.preview.show()
            self._refresh_preview()
        else:
            self.preview.hide()

    def _refresh_preview(self) -> None:
        if not self.preview_toggle.get_active():
            return
        html = render_html(
            self.editor.get_text(),
            css_href=self.project.get_css_relative_path(),
            margin_mm=self.project.get_pdf_margin_mm(),
        )
        self.preview.load_html(html, self.project.path)

    def _on_key_press(self, _widget, event) -> bool:
        if event.keyval == Gdk.KEY_s and event.state & Gdk.ModifierType.CONTROL_MASK:
            self.editor.save()
            self._flash_save_indicator()
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
        css_box = gtk.Box(orientation=gtk.Orientation.HORIZONTAL, spacing=4)
        css_label = gtk.Label(label=self._css_label_text())
        css_button = gtk.Button(label="Choose CSS file")
        css_button.connect("clicked", lambda _b: self._on_choose_css_clicked(dialog, css_label))
        css_box.pack_start(css_button, False, False, 0)
        css_box.pack_start(css_label, False, False, 0)
        content.add(css_box)

        content.add(gtk.Label(label="Editor font size:", xalign=0))
        font_size_spin = gtk.SpinButton.new_with_range(6, 48, 1)
        font_size_spin.set_value(self.project.get_font_size())
        content.add(font_size_spin)

        content.add(gtk.Label(label="PDF export margin (mm):", xalign=0))
        pdf_margin_spin = gtk.SpinButton.new_with_range(0, 50, 1)
        pdf_margin_spin.set_value(self.project.get_pdf_margin_mm())
        content.add(pdf_margin_spin)

        dialog.show_all()
        response = dialog.run()
        if response == gtk.ResponseType.OK:
            self.project.set_title(title_entry.get_text().strip() or None)
            self.subtitle_label.set_text(self._header_subtitle())

            self.project.set_font_size(font_size_spin.get_value_as_int())
            self.editor.set_font_size(font_size_spin.get_value_as_int())

            self.project.set_pdf_margin_mm(pdf_margin_spin.get_value_as_int())
            self._refresh_preview()
        dialog.destroy()

    def _on_choose_css_clicked(self, parent, css_label: gtk.Label) -> None:
        dialog = gtk.FileChooserDialog(
            title="Choose a CSS file", transient_for=parent, action=gtk.FileChooserAction.OPEN,
        )
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
