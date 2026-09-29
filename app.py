"""Local API used by the single-user desktop learning journal."""

from __future__ import annotations

import os
import logging
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from contextlib import closing
from datetime import date, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.background import BackgroundTask

from storage import backup_database, data_directory, prepare_shared_database


ROOT = Path(__file__).resolve().parent
logger = logging.getLogger("learning-recording")


def configure_logging() -> None:
    if logger.handlers:
        return
    log_dir = Path(os.getenv("LEARNING_LOG_DIR", data_directory() / "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def valid_day(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("日期必须为 YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError("日期必须为 YYYY-MM-DD")
    return value


def valid_link(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("成果链接必须是 http 或 https 地址")
    return value


class RecordInput(BaseModel):
    day: str
    category: str = Field(min_length=1, max_length=40)
    content: str = Field(min_length=1, max_length=2000)
    minutes: int | None = Field(default=None, ge=0, le=1440)
    link: str | None = Field(default=None, max_length=1000)

    @field_validator("day")
    @classmethod
    def check_day(cls, value: str) -> str:
        return valid_day(value)

    @field_validator("category", "content")
    @classmethod
    def check_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("内容不能为空")
        return value

    @field_validator("link")
    @classmethod
    def check_link(cls, value: str | None) -> str | None:
        return valid_link(value)


class MilestoneInput(BaseModel):
    day: str
    title: str = Field(min_length=1, max_length=100)
    detail: str = Field(default="", max_length=2000)

    @field_validator("day")
    @classmethod
    def check_day(cls, value: str) -> str:
        return valid_day(value)

    @field_validator("title", "detail")
    @classmethod
    def check_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("title")
    @classmethod
    def check_title(cls, value: str) -> str:
        if not value:
            raise ValueError("节点标题不能为空")
        return value


class ReviewInput(BaseModel):
    week_start: str
    learning: str = Field(default="", max_length=2000)
    blocker: str = Field(default="", max_length=2000)
    follow_up: str = Field(default="", max_length=1000)
    next_step: str = Field(default="", max_length=1000)

    @field_validator("week_start")
    @classmethod
    def check_week(cls, value: str) -> str:
        valid_day(value)
        if date.fromisoformat(value).weekday() != 0:
            raise ValueError("回顾须从周一开始")
        return value

    @field_validator("learning", "blocker", "follow_up", "next_step")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class ActivitySettingsInput(BaseModel):
    record_target: int = Field(default=8, ge=1, le=100)
    minutes_target: int = Field(default=600, ge=1, le=1440)


def create_app(db_path: Path | str | None = None, first_used_on: str | None = None) -> FastAPI:
    configure_logging()
    db_path = Path(db_path or os.getenv("LEARNING_DB_PATH") or prepare_shared_database())
    db_path.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.RLock()

    def ensure_schema(db: sqlite3.Connection, initial_day: str) -> None:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                minutes INTEGER,
                link TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_records_day ON records(day);
            CREATE INDEX IF NOT EXISTS idx_records_category_day ON records(category, day DESC, id DESC);
            CREATE TABLE IF NOT EXISTS milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_milestones_day ON milestones(day);
            CREATE TABLE IF NOT EXISTS weekly_reviews (
                week_start TEXT PRIMARY KEY,
                learning TEXT NOT NULL DEFAULT '',
                blocker TEXT NOT NULL DEFAULT '',
                follow_up TEXT NOT NULL DEFAULT '',
                next_step TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        review_columns = {row[1] for row in db.execute("PRAGMA table_info(weekly_reviews)")}
        for column in ("blocker", "follow_up"):
            if column not in review_columns:
                db.execute(f"ALTER TABLE weekly_reviews ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        db.execute("INSERT OR IGNORE INTO app_meta(key, value) VALUES ('first_used_on', ?)", (initial_day,))
        db.execute("INSERT OR IGNORE INTO app_meta(key, value) VALUES ('activity_record_target', '8')")
        db.execute("INSERT OR IGNORE INTO app_meta(key, value) VALUES ('activity_minutes_target', '600')")

    def activity_settings(db: sqlite3.Connection) -> dict:
        values = dict(db.execute("SELECT key, value FROM app_meta WHERE key IN ('activity_record_target', 'activity_minutes_target')"))
        try:
            return ActivitySettingsInput(record_target=int(values['activity_record_target']), minutes_target=int(values['activity_minutes_target'])).model_dump()
        except (KeyError, ValueError):
            return ActivitySettingsInput().model_dump()

    def first_day(db: sqlite3.Connection) -> str:
        return db.execute("SELECT value FROM app_meta WHERE key='first_used_on'").fetchone()[0]

    def check_allowed_day(db: sqlite3.Connection, day: str) -> None:
        if day < first_day(db) or day > date.today().isoformat():
            raise HTTPException(422, f"日期须在首次使用日 {first_day(db)} 与今天之间")

    @contextmanager
    def connection():
        with lock:
            db = sqlite3.connect(db_path, timeout=10)
            db.row_factory = sqlite3.Row
            try:
                yield db
                db.commit()
            finally:
                db.close()

    with connection() as db:
        ensure_schema(db, first_used_on or date.today().isoformat())

    app = FastAPI(title="学习记录", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/api/overview")
    def overview():
        with connection() as db:
            stats = dict(db.execute("SELECT COUNT(*) AS total_records, COUNT(DISTINCT day) AS active_days, COALESCE(SUM(minutes), 0) AS total_minutes FROM records").fetchone())
            settings = activity_settings(db)
            activity = {}
            for row in db.execute("SELECT day, COUNT(*) AS count, COALESCE(SUM(minutes), 0) AS minutes, COUNT(*) - COUNT(minutes) AS untimed_count FROM records GROUP BY day"):
                score = max(1, int(30 * min(row['count'] / settings['record_target'], 1) + 70 * min(row['minutes'] / settings['minutes_target'], 1) + 0.5))
                activity[row['day']] = {"count": row['count'], "minutes": row['minutes'], "untimed_count": row['untimed_count'], "score": score, "level": (score + 24) // 25}
            milestones = [dict(row) for row in db.execute("SELECT * FROM milestones ORDER BY day DESC, id DESC")]
            categories = [row[0] for row in db.execute("SELECT DISTINCT category FROM records ORDER BY category")]
            started_on = first_day(db)
        return {"stats": stats, "activity": activity, "activity_settings": settings, "milestones": milestones, "categories": categories, "first_used_on": started_on}

    @app.put("/api/activity-settings")
    def save_activity_settings(item: ActivitySettingsInput):
        with connection() as db:
            db.executemany("INSERT INTO app_meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", [("activity_record_target", str(item.record_target)), ("activity_minutes_target", str(item.minutes_target))])
        logger.info("activity.settings record_target=%s minutes_target=%s", item.record_target, item.minutes_target)
        return item.model_dump()

    @app.get("/api/records")
    def records_for_day(day: str):
        try:
            valid_day(day)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with connection() as db:
            check_allowed_day(db, day)
            return [dict(row) for row in db.execute("SELECT * FROM records WHERE day=? ORDER BY id DESC", (day,))]

    @app.get("/api/search")
    def search_records(
        query: str = "", category: str = "", from_day: str = "", to_day: str = "",
        page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=50),
    ):
        query, category = query.strip(), category.strip()
        if not any((query, category, from_day, to_day)):
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        for value in (from_day, to_day):
            if value:
                try:
                    valid_day(value)
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
        if from_day and to_day and from_day > to_day:
            raise HTTPException(422, "开始日期不能晚于结束日期")
        where = ["day >= ?", "day <= ?"]
        with connection() as db:
            params = [first_day(db), date.today().isoformat()]
            if query:
                where.append("(instr(lower(category), lower(?)) > 0 OR instr(lower(content), lower(?)) > 0)")
                params.extend([query, query])
            if category:
                where.append("category = ?")
                params.append(category)
            if from_day:
                where.append("day >= ?")
                params.append(from_day)
            if to_day:
                where.append("day <= ?")
                params.append(to_day)
            condition = " AND ".join(where)
            total = db.execute(f"SELECT COUNT(*) FROM records WHERE {condition}", params).fetchone()[0]
            items = [dict(row) for row in db.execute(
                f"SELECT * FROM records WHERE {condition} ORDER BY day DESC, id DESC LIMIT ? OFFSET ?",
                [*params, page_size, (page - 1) * page_size],
            )]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    @app.get("/api/review")
    def weekly_review(week_start: str):
        try:
            valid_day(week_start)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        start = date.fromisoformat(week_start)
        if start.weekday() != 0:
            raise HTTPException(422, "回顾须从周一开始")
        end = min(start + timedelta(days=6), date.today())
        with connection() as db:
            if end.isoformat() < first_day(db) or start > date.today():
                raise HTTPException(422, "该周不在使用日期范围内")
            stats = dict(db.execute("SELECT COUNT(*) AS total_records, COUNT(DISTINCT day) AS active_days, COALESCE(SUM(minutes), 0) AS total_minutes FROM records WHERE day BETWEEN ? AND ?", (week_start, end.isoformat())).fetchone())
            categories = [dict(row) for row in db.execute("SELECT category, COUNT(*) AS count FROM records WHERE day BETWEEN ? AND ? GROUP BY category ORDER BY count DESC, category", (week_start, end.isoformat()))]
            note = db.execute("SELECT learning, blocker, follow_up, next_step FROM weekly_reviews WHERE week_start=?", (week_start,)).fetchone()
            previous_week = (start - timedelta(days=7)).isoformat()
            previous = db.execute("SELECT next_step FROM weekly_reviews WHERE week_start=?", (previous_week,)).fetchone()
        return {"week_start": week_start, "week_end": end.isoformat(), **stats, "categories": categories, "learning": note["learning"] if note else "", "blocker": note["blocker"] if note else "", "follow_up": note["follow_up"] if note else "", "next_step": note["next_step"] if note else "", "previous_next_step": previous["next_step"] if previous else ""}

    @app.put("/api/review")
    def save_weekly_review(item: ReviewInput):
        with connection() as db:
            end = date.fromisoformat(item.week_start) + timedelta(days=6)
            if end.isoformat() < first_day(db) or item.week_start > date.today().isoformat():
                raise HTTPException(422, "该周不在使用日期范围内")
            db.execute("INSERT INTO weekly_reviews(week_start, learning, blocker, follow_up, next_step) VALUES (?, ?, ?, ?, ?) ON CONFLICT(week_start) DO UPDATE SET learning=excluded.learning, blocker=excluded.blocker, follow_up=excluded.follow_up, next_step=excluded.next_step", (item.week_start, item.learning, item.blocker, item.follow_up, item.next_step))
            logger.info("review.save week_start=%s", item.week_start)
        return {"saved": True}

    @app.post("/api/records", status_code=201)
    def add_record(item: RecordInput):
        with connection() as db:
            check_allowed_day(db, item.day)
            cursor = db.execute(
                "INSERT INTO records(day, category, content, minutes, link) VALUES (?, ?, ?, ?, ?)",
                (item.day, item.category, item.content, item.minutes, item.link),
            )
            logger.info("record.create id=%s day=%s", cursor.lastrowid, item.day)
            return dict(db.execute("SELECT * FROM records WHERE id = ?", (cursor.lastrowid,)).fetchone())

    @app.put("/api/records/{record_id}")
    def edit_record(record_id: int, item: RecordInput):
        with connection() as db:
            check_allowed_day(db, item.day)
            cursor = db.execute(
                "UPDATE records SET day=?, category=?, content=?, minutes=?, link=? WHERE id=?",
                (item.day, item.category, item.content, item.minutes, item.link, record_id),
            )
            if not cursor.rowcount:
                raise HTTPException(404, "记录不存在")
            logger.info("record.update id=%s day=%s", record_id, item.day)
            return dict(db.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone())

    @app.delete("/api/records/{record_id}", status_code=204)
    def delete_record(record_id: int):
        with connection() as db:
            if not db.execute("DELETE FROM records WHERE id = ?", (record_id,)).rowcount:
                raise HTTPException(404, "记录不存在")
            logger.info("record.delete id=%s", record_id)

    @app.post("/api/milestones", status_code=201)
    def add_milestone(item: MilestoneInput):
        with connection() as db:
            check_allowed_day(db, item.day)
            cursor = db.execute(
                "INSERT INTO milestones(day, title, detail) VALUES (?, ?, ?)",
                (item.day, item.title, item.detail),
            )
            logger.info("milestone.create id=%s day=%s", cursor.lastrowid, item.day)
            return dict(db.execute("SELECT * FROM milestones WHERE id = ?", (cursor.lastrowid,)).fetchone())

    @app.delete("/api/milestones/{milestone_id}", status_code=204)
    def delete_milestone(milestone_id: int):
        with connection() as db:
            if not db.execute("DELETE FROM milestones WHERE id = ?", (milestone_id,)).rowcount:
                raise HTTPException(404, "成长节点不存在")
            logger.info("milestone.delete id=%s", milestone_id)

    @app.get("/api/backup")
    def download_backup():
        with tempfile.NamedTemporaryFile(suffix=".db", dir=db_path.parent, delete=False) as handle:
            snapshot = Path(handle.name)
        try:
            with lock:
                backup_database(db_path, snapshot)
        except Exception:
            snapshot.unlink(missing_ok=True)
            raise
        logger.info("backup.download")
        return FileResponse(
            snapshot,
            media_type="application/x-sqlite3",
            filename=f"shiguang-{date.today():%Y%m%d}.db",
            background=BackgroundTask(lambda: snapshot.unlink(missing_ok=True)),
        )

    @app.post("/api/backup-local")
    def save_backup():
        backup_path = db_path.parent / "backups" / f"shiguang-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
        with lock:
            backup_database(db_path, backup_path)
        logger.info("backup.local path=%s", backup_path.name)
        return {"path": str(backup_path)}

    @app.post("/api/restore")
    async def restore_backup(request: Request):
        limit = 50 * 1024 * 1024
        if int(request.headers.get("content-length", "0")) > limit:
            raise HTTPException(413, "备份文件超过 50 MB")
        payload = await request.body()
        if not payload or len(payload) > limit:
            raise HTTPException(413, "备份文件为空或超过 50 MB")
        with tempfile.NamedTemporaryFile(suffix=".db", dir=db_path.parent, delete=False) as handle:
            incoming = Path(handle.name)
            handle.write(payload)
        try:
            try:
                with closing(sqlite3.connect(incoming)) as source:
                    if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError("备份文件完整性检查未通过")
                    required = {
                        "records": {"id", "day", "category", "content", "minutes", "link", "created_at"},
                        "milestones": {"id", "day", "title", "detail"},
                    }
                    for table, columns in required.items():
                        actual = {row[1] for row in source.execute(f"PRAGMA table_info({table})")}
                        if not columns.issubset(actual):
                            raise ValueError("文件不是有效的拾光备份")
            except (sqlite3.DatabaseError, ValueError) as exc:
                raise HTTPException(422, str(exc)) from exc

            with lock:
                with connection() as db:
                    previous_first_day = first_day(db)
                safety = db_path.parent / "backups" / f"before-restore-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
                backup_database(db_path, safety)
                backup_database(incoming, db_path)
                with connection() as db:
                    ensure_schema(db, previous_first_day)
                    restored_first_day = first_day(db)
                    if previous_first_day < restored_first_day:
                        db.execute("UPDATE app_meta SET value=? WHERE key='first_used_on'", (previous_first_day,))
            logger.info("backup.restore safety=%s", safety.name)
            return {"restored": True, "safety_backup": str(safety)}
        finally:
            incoming.unlink(missing_ok=True)

    return app


app = create_app()
