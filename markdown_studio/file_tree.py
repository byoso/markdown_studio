"""Left-side file tree widget: shows the whole project folder and supports
reordering .md files by swapping their (xxx) prefix with a neighbor."""
from __future__ import annotations

from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk as gtk, GObject

from .project import parse_order_prefix, set_order_prefix


class FileTree(gtk.Box):
    __gsignals__ = {
        "file-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    COL_NAME, COL_PATH, COL_IS_DIR = range(3)

    def __init__(self, root_path: str | Path):
        super().__init__(orientation=gtk.Orientation.VERTICAL)
        self.root_path = Path(root_path)

        toolbar = gtk.Box(orientation=gtk.Orientation.HORIZONTAL, spacing=4)
        up_button = gtk.Button(label="\u25b2")
        up_button.set_tooltip_text("Move selected file up (swap prefix with previous)")
        up_button.connect("clicked", lambda _b: self._swap_with_neighbor(-1))
        down_button = gtk.Button(label="\u25bc")
        down_button.set_tooltip_text("Move selected file down (swap prefix with next)")
        down_button.connect("clicked", lambda _b: self._swap_with_neighbor(1))
        new_folder_button = gtk.Button(label="New folder")
        new_folder_button.connect("clicked", lambda _b: self._on_new_folder())
        toolbar.pack_start(up_button, False, False, 0)
        toolbar.pack_start(down_button, False, False, 0)
        toolbar.pack_start(new_folder_button, False, False, 0)
        self.pack_start(toolbar, False, False, 0)

        self.store = gtk.TreeStore(str, str, bool)
        self.tree_view = gtk.TreeView(model=self.store)

        column = gtk.TreeViewColumn("Files")
        icon_renderer = gtk.CellRendererPixbuf()
        column.pack_start(icon_renderer, False)
        column.set_cell_data_func(icon_renderer, self._render_icon)
        text_renderer = gtk.CellRendererText()
        column.pack_start(text_renderer, True)
        column.add_attribute(text_renderer, "text", self.COL_NAME)
        self.tree_view.append_column(column)
        self.tree_view.connect("row-activated", self._on_row_activated)

        scroll = gtk.ScrolledWindow()
        scroll.add(self.tree_view)
        self.pack_start(scroll, True, True, 0)

        self.refresh()

    def refresh(self) -> None:
        self.store.clear()
        self._populate(self.root_path, None)

    def _populate(self, folder: Path, parent_iter) -> None:
        try:
            entries = sorted(folder.iterdir(), key=self._sort_key)
        except OSError:
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            tree_iter = self.store.append(parent_iter, [entry.name, str(entry), entry.is_dir()])
            if entry.is_dir():
                self._populate(entry, tree_iter)

    @staticmethod
    def _sort_key(p: Path):
        """Directories first, then files ordered by their (xxx) prefix, then alphabetically."""
        is_dir = p.is_dir()
        prefix = parse_order_prefix(p.name)
        return (
            0 if is_dir else 1,
            0 if prefix is not None else 1,
            prefix if prefix is not None else 0,
            p.name.lower(),
        )

    def _render_icon(self, _column, cell, model, tree_iter, _data) -> None:
        is_dir = model[tree_iter][self.COL_IS_DIR]
        cell.set_property("icon-name", "folder" if is_dir else "text-x-generic")

    def _on_row_activated(self, tree_view, path, column) -> None:
        tree_iter = self.store.get_iter(path)
        if not self.store[tree_iter][self.COL_IS_DIR]:
            self.emit("file-selected", self.store[tree_iter][self.COL_PATH])

    def _get_selected_path(self) -> Path | None:
        selection = self.tree_view.get_selection()
        model, tree_iter = selection.get_selected()
        if tree_iter is None:
            return None
        return Path(model[tree_iter][self.COL_PATH])

    def _on_new_folder(self) -> None:
        parent = self._get_selected_path()
        target_dir = parent if parent is not None and parent.is_dir() else self.root_path

        dialog = gtk.Dialog(title="New folder", transient_for=self.get_toplevel(), flags=0)
        dialog.add_buttons(gtk.STOCK_CANCEL, gtk.ResponseType.CANCEL, gtk.STOCK_OK, gtk.ResponseType.OK)
        entry = gtk.Entry()
        entry.set_placeholder_text("Folder name")
        dialog.get_content_area().add(entry)
        dialog.show_all()
        response = dialog.run()
        name = entry.get_text().strip()
        dialog.destroy()

        if response == gtk.ResponseType.OK and name:
            (target_dir / name).mkdir(parents=True, exist_ok=True)
            self.refresh()

    def _swap_with_neighbor(self, direction: int) -> None:
        selected = self._get_selected_path()
        if selected is None or selected.suffix != ".md":
            return

        siblings = sorted(
            (p for p in selected.parent.iterdir() if p.is_file() and p.suffix == ".md"),
            key=lambda p: (parse_order_prefix(p.name) is None, parse_order_prefix(p.name) or 0, p.name),
        )
        index = siblings.index(selected)
        neighbor_index = index + direction
        if not (0 <= neighbor_index < len(siblings)):
            return

        self._swap_prefixes(selected, siblings[neighbor_index])
        self.refresh()

    @staticmethod
    def _swap_prefixes(file_a: Path, file_b: Path) -> None:
        prefix_a = parse_order_prefix(file_a.name)
        prefix_b = parse_order_prefix(file_b.name)
        name_a = set_order_prefix(file_a.name, prefix_b)
        name_b = set_order_prefix(file_b.name, prefix_a)

        # go through a temp name to avoid clobbering when the two target names collide
        temp_a = file_a.with_name(f".tmp_swap_{file_a.name}")
        file_a.rename(temp_a)
        file_b.rename(file_b.with_name(name_b))
        temp_a.rename(file_a.with_name(name_a))
