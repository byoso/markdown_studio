"""Application-level database: tracks known Markdown Studio project folders."""
from __future__ import annotations

from pathlib import Path

from silly_engine.jsondb import JsonDb

APP_DB_PATH = Path(__file__).resolve().parent.parent / "app_db.json"


class AppDatabase:
    PROJECTS_COLLECTION = "projects"

    def __init__(self, path: str | Path = APP_DB_PATH):
        self.db = JsonDb(path, autosave=True, version="1.0.0")

    def list_projects(self) -> list[dict]:
        """Return known projects, pruning entries whose folder no longer exists on disk."""
        collection = self.db.collection(self.PROJECTS_COLLECTION)
        projects = []
        for item in collection.all():
            if Path(item.data["path"]).is_dir():
                projects.append(item.data)
            else:
                collection.delete(item)
        return projects

    def add_project(self, path: str | Path) -> None:
        """Register a project folder, ignoring it if already known."""
        path_str = str(Path(path))
        collection = self.db.collection(self.PROJECTS_COLLECTION)
        for item in collection.all():
            if item.data.get("path") == path_str:
                return
        collection.insert({"path": path_str, "name": Path(path_str).name})
