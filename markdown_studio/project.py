"""Project model: a Markdown Studio project is a folder containing .md files,
optional assets, and a `.studio/config.json` configuration database."""
from __future__ import annotations

import os
import re
from pathlib import Path

from silly_engine.jsondb import JsonDb

PREFIX_RE = re.compile(r"^\((\d+)\)\s*")
PREFIX_WIDTH = 3


def parse_order_prefix(filename: str) -> int | None:
    """Extract the leading "(xxx)" numeric prefix from a filename, if present."""
    match = PREFIX_RE.match(filename)
    return int(match.group(1)) if match else None


def strip_order_prefix(filename: str) -> str:
    return PREFIX_RE.sub("", filename)


def set_order_prefix(filename: str, prefix: int | None) -> str:
    rest = strip_order_prefix(filename)
    return f"({prefix:0{PREFIX_WIDTH}d}) {rest}" if prefix is not None else rest


class Project:
    """A Markdown Studio project stored as a folder on disk."""

    CONFIG_DIR = ".studio"
    CONFIG_FILE = "config.json"
    SETTINGS_COLLECTION = "settings"
    EXPORTS_DIR = "exports"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        config_path = self.path / self.CONFIG_DIR / self.CONFIG_FILE
        self.db = JsonDb(config_path, autosave=True, version="1.0.0")

    @classmethod
    def create(cls, path: str | Path) -> Project:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        return cls(path)

    @classmethod
    def load(cls, path: str | Path) -> Project:
        return cls(Path(path))

    def list_markdown_files(self) -> list[Path]:
        """Return .md files in the project root, ordered by their (xxx) prefix.

        Files without a prefix are sorted last, alphabetically among themselves.
        """
        files = [p for p in self.path.rglob("*.md") if p.is_file()]

        def sort_key(p: Path):
            prefix = parse_order_prefix(p.name)
            return (
                prefix is None,
                prefix if prefix is not None else 0,
                p.name,
                str(p.relative_to(self.path)),
            )

        return sorted(files, key=sort_key)

    def _update_settings(self, **fields) -> None:
        """Merge the given fields into the project's settings singleton."""
        collection = self.db.collection(self.SETTINGS_COLLECTION)
        existing = collection.first()
        if existing is None:
            collection.insert(fields)
        else:
            existing.update(fields)

    def get_title(self) -> str | None:
        settings = self.db.collection(self.SETTINGS_COLLECTION).first()
        return settings.data.get("title") if settings is not None else None

    def set_title(self, title: str | None) -> None:
        self._update_settings(title=title)

    def get_css_relative_path(self) -> str | None:
        """Return the project's stylesheet path, relative to the project root."""
        settings = self.db.collection(self.SETTINGS_COLLECTION).first()
        return settings.data.get("css_path") if settings is not None else None

    def set_css_path(self, css_path: str | Path | None) -> None:
        """Store the stylesheet path as relative to the project root."""
        rel = os.path.relpath(Path(css_path), self.path) if css_path is not None else None
        self._update_settings(css_path=rel)

    DEFAULT_FONT_SIZE = 15
    DEFAULT_SPELLCHECK_LANGUAGES = ["en"]

    def get_font_size(self) -> int:
        settings = self.db.collection(self.SETTINGS_COLLECTION).first()
        if settings is None:
            return self.DEFAULT_FONT_SIZE
        return settings.data.get("font_size", self.DEFAULT_FONT_SIZE)

    def set_font_size(self, font_size: int) -> None:
        self._update_settings(font_size=font_size)

    def get_spellcheck_languages(self) -> list[str]:
        settings = self.db.collection(self.SETTINGS_COLLECTION).first()
        if settings is None:
            return self.DEFAULT_SPELLCHECK_LANGUAGES.copy()
        languages = settings.data.get("spellcheck_languages", self.DEFAULT_SPELLCHECK_LANGUAGES)
        return [language for language in languages if language in ("en", "fr")]

    def set_spellcheck_languages(self, languages: list[str]) -> None:
        selected = [language for language in ("en", "fr") if language in languages]
        self._update_settings(spellcheck_languages=selected)

    def get_exports_dir(self) -> Path:
        """Return the project's PDF export folder, creating it if needed."""
        exports_dir = self.path / self.EXPORTS_DIR
        exports_dir.mkdir(exist_ok=True)
        return exports_dir
