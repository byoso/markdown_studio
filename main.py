#! /usr/bin/env python3
# -*- coding : utf-8 -*-

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk as gtk

from markdown_studio.window import MainWindow


def choose_project_folder():
    dialog = gtk.FileChooserDialog(
        title="Open or create a project folder",
        action=gtk.FileChooserAction.SELECT_FOLDER,
    )
    dialog.add_buttons(gtk.STOCK_CANCEL, gtk.ResponseType.CANCEL, "Select", gtk.ResponseType.OK)
    response = dialog.run()
    folder = dialog.get_filename()
    dialog.destroy()
    return folder if response == gtk.ResponseType.OK else None


def main():
    project_path = choose_project_folder()
    if not project_path:
        return

    window = MainWindow(project_path)
    window.show_all()
    window.connect("delete-event", gtk.main_quit)
    gtk.main()


if __name__ == "__main__":
    main()
