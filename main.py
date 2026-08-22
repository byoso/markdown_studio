#! /usr/bin/env python3
# -*- coding : utf-8 -*-

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk as gtk
from pathlib import Path

from markdown_studio.app_db import AppDatabase
from markdown_studio.window import MainWindow


def choose_new_project_folder(parent=None):
    dialog = gtk.FileChooserDialog(
        title="Open or create a project folder",
        action=gtk.FileChooserAction.SELECT_FOLDER,
        transient_for=parent,
    )
    dialog.add_buttons(gtk.STOCK_CANCEL, gtk.ResponseType.CANCEL, "Select", gtk.ResponseType.OK)
    response = dialog.run()
    folder = dialog.get_filename()
    dialog.destroy()
    return folder if response == gtk.ResponseType.OK else None


def _remove_known_project(app_db, parent, list_box, row):
    dialog = gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        message_type=gtk.MessageType.QUESTION,
        buttons=gtk.ButtonsType.CANCEL,
        text="Remove this project from the list?",
    )
    dialog.add_button("Remove", gtk.ResponseType.OK)
    dialog.format_secondary_text("The project folder and its files will not be deleted.")
    response = dialog.run()
    dialog.destroy()

    if response == gtk.ResponseType.OK:
        app_db.remove_project(row.project_path)
        list_box.remove(row)


def choose_project(app_db, parent=None):
    """Let the user pick a known project, or browse for a new/existing one."""
    dialog = gtk.Dialog(title="Open a Markdown Studio project", transient_for=parent)
    dialog.set_default_size(420, 320)
    dialog.add_buttons(
        gtk.STOCK_CANCEL, gtk.ResponseType.CANCEL,
        "Browse...", gtk.ResponseType.APPLY,
        "Open", gtk.ResponseType.OK,
    )
    dialog.set_default_response(gtk.ResponseType.OK)

    content = dialog.get_content_area()
    content.set_spacing(6)
    content.set_border_width(12)
    content.add(gtk.Label(label="Known projects:", xalign=0))

    list_box = gtk.ListBox()
    list_box.set_selection_mode(gtk.SelectionMode.SINGLE)
    for project in app_db.list_projects():
        row = gtk.ListBoxRow()
        box = gtk.Box(orientation=gtk.Orientation.HORIZONTAL, spacing=6)
        box.pack_start(gtk.Label(label=project["name"], xalign=0), False, False, 2)

        delete_button = gtk.Button()
        delete_button.add(gtk.Image.new_from_icon_name("user-trash-symbolic", gtk.IconSize.BUTTON))
        delete_button.set_relief(gtk.ReliefStyle.NONE)
        delete_button.set_tooltip_text("Remove project from the list")
        delete_button.connect(
            "clicked",
            lambda _button, current_row=row: _remove_known_project(
                app_db, dialog, list_box, current_row,
            ),
        )
        box.pack_end(delete_button, False, False, 2)
        row.add(box)
        row.project_path = project["path"]
        list_box.add(row)
    list_box.connect("row-activated", lambda _lb, _row: dialog.response(gtk.ResponseType.OK))

    scroll = gtk.ScrolledWindow()
    scroll.set_min_content_height(200)
    scroll.add(list_box)
    content.add(scroll)

    dialog.show_all()

    selected_path = None
    response = dialog.run()
    if response == gtk.ResponseType.OK:
        row = list_box.get_selected_row()
        if row is not None:
            selected_path = row.project_path
    elif response == gtk.ResponseType.APPLY:
        new_path = choose_new_project_folder(dialog)
        if new_path:
            app_db.add_project(new_path)
            selected_path = new_path

    dialog.destroy()
    return selected_path


def main():
    gtk.Window.set_default_icon_from_file(str(Path(__file__).parent / "icon.png"))
    app_db = AppDatabase()
    project_path = choose_project(app_db)
    if not project_path:
        return

    window = None

    def change_project():
        selected_path = choose_project(app_db, parent=window)
        if not selected_path:
            return

        window.change_project(selected_path)

    window = MainWindow(project_path, on_change_project=change_project)
    window.show_all()
    window.connect("delete-event", gtk.main_quit)
    gtk.main()


if __name__ == "__main__":
    main()
