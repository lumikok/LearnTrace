import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

_import_temp = tempfile.TemporaryDirectory()
os.environ["LEARNING_DB_PATH"] = str(Path(_import_temp.name) / "module.db")
os.environ["LEARNING_LOG_DIR"] = str(Path(__file__).resolve().parents[1] / "logs")

from app import create_app
from storage import prepare_shared_database


class AppFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        self.client = TestClient(create_app(self.db_path, first_used_on="2026-09-22"))

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_record_lifecycle_and_persistence(self):
        payload = {"day": "2026-09-24", "category": "算法", "content": "复盘二分查找", "minutes": 45, "link": "https://example.com/note"}
        created = self.client.post("/api/records", json=payload)
        self.assertEqual(created.status_code, 201)
        record_id = created.json()["id"]
        payload.update({"content": "独立完成二分查找", "minutes": 60})
        self.assertEqual(self.client.put(f"/api/records/{record_id}", json=payload).status_code, 200)
        fresh_client = TestClient(create_app(self.db_path))
        overview = fresh_client.get("/api/overview").json()
        self.assertNotIn("records", overview)
        self.assertEqual(overview["stats"]["total_records"], 1)
        saved = fresh_client.get("/api/records?day=2026-09-24").json()[0]
        self.assertEqual(saved["content"], "独立完成二分查找")
        self.assertEqual(saved["minutes"], 60)
        self.assertEqual(self.client.delete(f"/api/records/{record_id}").status_code, 204)
        self.assertEqual(self.client.get("/api/records?day=2026-09-24").json(), [])
        fresh_client.close()

    def test_activity_updates_with_record_changes(self):
        day = "2026-09-24"
        self.assertNotIn(day, self.client.get("/api/overview").json()["activity"])
        ids = []
        for n in range(5):
            response = self.client.post("/api/records", json={"day": day, "category": "算法", "content": f"记录 {n}"})
            ids.append(response.json()["id"])
            activity = self.client.get("/api/overview").json()["activity"][day]
            self.assertEqual(activity, {"count": n + 1, "level": min(n + 1, 4)})
        self.assertEqual(self.client.put(f"/api/records/{ids[0]}", json={"day": "2026-09-23", "category": "算法", "content": "改日期"}).status_code, 200)
        activity = self.client.get("/api/overview").json()["activity"]
        self.assertEqual(activity[day], {"count": 4, "level": 4})
        self.assertEqual(activity["2026-09-23"], {"count": 1, "level": 1})
        for record_id in ids[1:]:
            self.assertEqual(self.client.delete(f"/api/records/{record_id}").status_code, 204)
        self.assertNotIn(day, self.client.get("/api/overview").json()["activity"])

    def test_milestone_and_validation(self):
        milestone = self.client.post("/api/milestones", json={"day": "2026-09-24", "title": "第一个项目", "detail": "独立完成"})
        self.assertEqual(milestone.status_code, 201)
        overview = self.client.get("/api/overview").json()
        self.assertEqual(len(overview["milestones"]), 1)
        self.assertEqual(self.client.delete(f"/api/milestones/{milestone.json()['id']}").status_code, 204)
        self.assertEqual(self.client.post("/api/records", json={"day":"2026-09-24","category":"算法","content":"测试","link":"javascript:alert(1)"}).status_code, 422)
        self.assertEqual(self.client.post("/api/milestones", json={"day":"2026-09-24","title":"   "}).status_code, 422)

    def test_first_use_date_and_backup_restore(self):
        first_day = self.client.get("/api/overview").json()["first_used_on"]
        self.assertEqual(first_day, "2026-09-22")
        invalid_day = {"day": "2026-09-21", "category": "算法", "content": "太早"}
        self.assertEqual(self.client.post("/api/records", json=invalid_day).status_code, 422)
        self.assertEqual(self.client.post("/api/milestones", json={"day":"2026-09-21", "title":"太早"}).status_code, 422)
        created = self.client.post("/api/records", json={"day":"2026-09-24", "category":"算法", "content":"需要保留"}).json()
        backup = self.client.get("/api/backup")
        self.assertEqual(backup.status_code, 200)
        self.assertTrue(backup.content.startswith(b"SQLite format 3"))
        local = self.client.post("/api/backup-local").json()
        self.assertTrue(Path(local["path"]).is_file())
        self.assertEqual(self.client.delete(f"/api/records/{created['id']}").status_code, 204)
        restored = self.client.post("/api/restore", content=backup.content, headers={"Content-Type":"application/octet-stream"})
        self.assertEqual(restored.status_code, 200)
        self.assertTrue(Path(restored.json()["safety_backup"]).is_file())
        self.assertEqual(self.client.get("/api/records?day=2026-09-24").json()[0]["content"], "需要保留")
        self.assertEqual(self.client.post("/api/restore", content=b"invalid").status_code, 422)
        self.assertEqual(len(self.client.get("/api/records?day=2026-09-24").json()), 1)

    def test_search_requires_filter_and_pages_results(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            db.executemany("INSERT INTO records(day, category, content) VALUES (?, ?, ?)", [("2026-09-24", "算法", f"练习 {n}") for n in range(45)])
            db.commit()
        self.assertEqual(self.client.get("/api/search").json()["items"], [])
        first = self.client.get("/api/search?category=算法&page=1").json()
        second = self.client.get("/api/search?category=算法&page=2").json()
        third = self.client.get("/api/search?category=算法&page=3").json()
        self.assertEqual([len(first["items"]), len(second["items"]), len(third["items"])], [20, 20, 5])
        self.assertEqual(first["total"], 45)
        self.assertEqual(len({item["id"] for page in (first, second, third) for item in page["items"]}), 45)
        self.assertEqual(self.client.get("/api/search?query=练习 4").json()["total"], 6)
        self.assertEqual(self.client.get("/api/search?from_day=2026-09-25&to_day=2026-09-24").status_code, 422)
        self.assertEqual(self.client.get("/api/search?category=算法&page_size=100").status_code, 422)

    def test_weekly_review_uses_records_and_saves_reflection(self):
        self.client.post("/api/records", json={"day": "2026-09-24", "category": "算法", "content": "理解边界", "minutes": 45})
        self.client.post("/api/records", json={"day": "2026-09-25", "category": "算法", "content": "自己实现", "minutes": 30})
        review = self.client.get("/api/review?week_start=2026-09-21").json()
        self.assertEqual((review["total_records"], review["active_days"], review["total_minutes"]), (2, 2, 75))
        self.assertEqual(review["learning"], "")
        self.assertEqual(self.client.put("/api/review", json={"week_start": "2026-09-21", "learning": "弄懂边界", "next_step": "独立完成两题"}).status_code, 200)
        self.assertEqual(self.client.get("/api/review?week_start=2026-09-21").json()["next_step"], "独立完成两题")
        reopened = TestClient(create_app(self.db_path))
        self.assertEqual(reopened.get("/api/review?week_start=2026-09-21").json()["learning"], "弄懂边界")
        reopened.close()
        self.assertEqual(self.client.get("/api/review?week_start=2026-09-22").status_code, 422)


class DesktopDataTests(unittest.TestCase):
    def test_fresh_install_records_first_day_once(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fresh.db"
            first = TestClient(create_app(path))
            self.assertEqual(first.get("/api/overview").json()["first_used_on"], date.today().isoformat())
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            self.assertEqual(first.post("/api/records", json={"day": yesterday, "category": "测试", "content": "过去"}).status_code, 422)
            first.close()
            second = TestClient(create_app(path, first_used_on=yesterday))
            self.assertEqual(second.get("/api/overview").json()["first_used_on"], date.today().isoformat())
            second.close()

    def test_shared_database_merges_colliding_ids_once(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.db"
            target = Path(folder) / "shared" / "learning.db"
            create_app(source, first_used_on="2026-09-24")
            create_app(target, first_used_on="2026-09-24")
            with closing(sqlite3.connect(source)) as db:
                db.execute("INSERT INTO records(id, day, category, content) VALUES (1, '2026-09-24', '算法', '浏览器记录')")
                db.commit()
            with closing(sqlite3.connect(target)) as db:
                db.execute("INSERT INTO records(id, day, category, content) VALUES (1, '2026-09-24', '英语', '桌面记录')")
                db.commit()
            with patch("storage.legacy_database", return_value=source), patch("storage.data_directory", return_value=target.parent):
                self.assertEqual(prepare_shared_database(), target)
                self.assertEqual(prepare_shared_database(), target)
            with closing(sqlite3.connect(target)) as db:
                rows = db.execute("SELECT content FROM records ORDER BY id").fetchall()
                self.assertEqual([row[0] for row in rows], ["桌面记录", "浏览器记录"])
                self.assertEqual(db.execute("SELECT value FROM app_meta WHERE key='first_used_on'").fetchone()[0], "2026-09-24")
            self.assertEqual(len(list((target.parent / "backups").glob("before-unify-*.db"))), 1)


if __name__ == "__main__":
    unittest.main()
