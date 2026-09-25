"""Shared local database location and one-time migration from the early project build."""

from __future__ import annotations

import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path


PROJECT_FIRST_DAY = "2026-09-24"
APP_FOLDER = "ShiGuangLearning"


def data_directory() -> Path:
    override = os.getenv("LEARNING_DATA_DIR") or os.getenv("LEARNING_DESKTOP_DATA_DIR")
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_FOLDER


def legacy_database() -> Path | None:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        if len(executable.parents) < 3:
            return None
        project = executable.parents[2]
    else:
        project = Path(__file__).resolve().parent
    candidate = project / "data" / "learning.db"
    return candidate if (project / "app.py").is_file() and candidate.is_file() else None


def backup_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source)) as source_db, closing(sqlite3.connect(destination)) as target_db:
        source_db.backup(target_db)


def _table_exists(db: sqlite3.Connection, name: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _merge_rows(target: sqlite3.Connection, source: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> None:
    if not (_table_exists(target, table) and _table_exists(source, table)):
        return
    fields = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    for row in source.execute(f"SELECT id, {fields} FROM {table} ORDER BY id"):
        existing = target.execute(f"SELECT {fields} FROM {table} WHERE id=?", (row[0],)).fetchone()
        if existing is None:
            target.execute(f"INSERT INTO {table}(id, {fields}) VALUES (?, {placeholders})", tuple(row))
        elif tuple(existing) != tuple(row[1:]):
            target.execute(f"INSERT INTO {table}({fields}) VALUES ({placeholders})", tuple(row[1:]))


def prepare_shared_database() -> Path:
    folder = data_directory()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "learning.db"
    source = legacy_database()
    if source and source.resolve() == target.resolve():
        source = None

    if not target.exists() and source:
        backup_database(source, target)

    if target.exists():
        with closing(sqlite3.connect(target)) as db:
            db.execute("CREATE TABLE IF NOT EXISTS app_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO app_meta(key, value) VALUES ('first_used_on', ?)", (PROJECT_FIRST_DAY,))
            migrated = db.execute("SELECT value FROM app_meta WHERE key='legacy_project_merged'").fetchone()
            if source and not migrated:
                safety = folder / "backups" / f"before-unify-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
                backup_database(target, safety)
                with closing(sqlite3.connect(source)) as old:
                    _merge_rows(db, old, "records", ("day", "category", "content", "minutes", "link", "created_at"))
                    _merge_rows(db, old, "milestones", ("day", "title", "detail"))
                    if _table_exists(db, "day_intensity") and _table_exists(old, "day_intensity"):
                        db.executemany(
                            "INSERT OR IGNORE INTO day_intensity(day, level) VALUES (?, ?)",
                            old.execute("SELECT day, level FROM day_intensity").fetchall(),
                        )
                db.execute("INSERT INTO app_meta(key, value) VALUES ('legacy_project_merged', '1')")
            db.commit()
    return target
