import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from layout import PageLayout
from storage import Entry, Page, Storage, pages_to_text

D = dt.date(2026, 11, 10)


class FakeClock:
    def __init__(self, t="2026-11-10T09:00:00"):
        self.t = t

    def __call__(self):
        return self.t


def sample_page(date=D):
    return Page(
        date,
        schedule=["21:00~22:00 새 일정", "", "09:30 회의", ""],
        journal=[Entry("[09:12]", "아침 회의 정리"), Entry("", "이어서 쓴 줄"),
                 Entry("업무 후", ""), Entry("[19:05]", "퇴근 후 메모"), Entry()],
        todo=["서류 검토", ""],
    )


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.clock = FakeClock()
        self.s = Storage(self.dir / "a" / "journal.db", clock=self.clock)

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def test_roundtrip(self):
        self.s.save_page(sample_page())
        p = self.s.get_page(D)
        self.assertEqual(p.schedule, ["21:00~22:00 새 일정", "", "09:30 회의"])  # 끝 빈 줄만 정리
        self.assertEqual(len(p.journal), 4)
        self.assertEqual(p.journal[2], Entry("업무 후", ""))
        self.assertEqual(p.todo, ["서류 검토"])
        self.assertEqual(p.updated, "2026-11-10T09:00:00")
        self.assertEqual([i.title for i in p.schedule_items()], ["회의", "새 일정"])

    def test_empty_page_not_stored(self):
        self.s.save_page(sample_page())
        self.s.save_page(Page(D, schedule=["  "], journal=[Entry()]))
        self.assertTrue(self.s.get_page(D).is_empty())
        self.assertEqual(self.s.dates_with_content(2026, 11), set())

    def test_month_dots_and_upcoming(self):
        self.s.save_page(sample_page())
        self.s.save_page(Page(dt.date(2026, 11, 20), journal=[Entry("[10:00]", "x")]))
        self.s.save_page(Page(dt.date(2026, 12, 1), schedule=["10:00 다음달"]))
        self.assertEqual(self.s.dates_with_content(2026, 11), {D, dt.date(2026, 11, 20)})
        self.assertEqual(self.s.dates_with_schedule(2026, 11), {D})
        up = self.s.upcoming(dt.date(2026, 11, 11), limit=3)
        self.assertEqual([(d, i.title) for d, i in up], [(dt.date(2026, 12, 1), "다음달")])
        self.assertEqual(len(self.s.upcoming(D, limit=1)), 1)

    def test_previous_todo(self):
        self.s.save_page(sample_page())
        self.assertEqual(self.s.previous_todo(dt.date(2026, 11, 12)), ["서류 검토"])
        self.assertEqual(self.s.previous_todo(D), [])

    def test_layout_setting(self):
        self.assertEqual(self.s.load_layout(), PageLayout())
        l = PageLayout(schedule_lines=7, journal_lines=15)
        self.s.save_layout(l)
        self.assertEqual(self.s.load_layout(), l)

    def test_export_import_merge(self):
        self.s.save_page(sample_page())
        self.s.save_page(Page(dt.date(2026, 11, 11), todo=["오래된 것"]))
        out = self.dir / "backup.json"
        self.assertEqual(self.s.export_json(out), 2)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["format"], "memo-journal")
        self.assertIn("새 일정", out.read_text(encoding="utf-8"))  # 한글 그대로 저장

        other = Storage(self.dir / "b.db", clock=FakeClock("2026-11-11T08:00:00"))
        other.save_page(Page(dt.date(2026, 11, 11), todo=["다른 PC에서 고침"]))  # 더 최신
        other.save_page(Page(D, todo=["옛날"]))
        other.db.execute("UPDATE pages SET updated='2026-11-01T00:00:00' WHERE date=?", (D.isoformat(),))
        other.db.commit()
        r = other.import_json(out)
        self.assertEqual((r.added, r.updated, r.skipped), (0, 1, 1))
        self.assertEqual(other.get_page(D).todo, ["서류 검토"])
        self.assertEqual(other.get_page(dt.date(2026, 11, 11)).todo, ["다른 PC에서 고침"])
        self.assertEqual(other.get_page(D).updated, "2026-11-10T09:00:00")  # 원래 시각 유지

        fresh = Storage(self.dir / "c.db")
        self.assertEqual(fresh.import_json(out).added, 2)
        fresh.close()
        other.close()

    def test_bold_underline_marks(self):
        p = sample_page()
        p.fmt = {"journal": [[0, 0, 2, "b"], [3, 1, 2, "u"], [9, 0, 1, "b"]],  # 9번 문단은 없음 → 버림
                 "todo": [[0, 0, 2, "x"], [0, 0, 0, "b"], ["a"]],               # 잘못된 값 → 버림
                 "schedule": [[2, 0, 5, "u"]]}
        self.s.save_page(p)
        got = self.s.get_page(D)
        self.assertEqual(got.fmt, {"journal": [[0, 0, 2, "b"], [3, 1, 2, "u"]], "schedule": [[2, 0, 5, "u"]]})
        out = self.dir / "f.json"
        self.s.export_json(out)
        other = Storage(self.dir / "f.db")
        other.import_json(out)
        self.assertEqual(other.get_page(D).fmt, got.fmt)
        other.close()
        self.assertNotIn("fmt", Page(D, todo=["x"]).to_json())  # 서식 없으면 키 없음

    def test_old_db_without_fmt_column(self):
        import sqlite3
        path = self.dir / "old.db"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE pages (date TEXT PRIMARY KEY, schedule TEXT NOT NULL DEFAULT '', "
                   "journal TEXT NOT NULL DEFAULT '[]', todo TEXT NOT NULL DEFAULT '', updated TEXT NOT NULL)")
        db.execute("INSERT INTO pages VALUES('2026-11-10', '', '[]', '옛 할 일', '2026-11-10T09:00:00')")
        db.commit()
        db.close()
        s = Storage(path)
        self.assertEqual(s.get_page(D).todo, ["옛 할 일"])
        self.assertEqual(s.get_page(D).fmt, {})
        s.close()

    def test_range_count_and_period_export(self):
        for day in (1, 10, 20):
            self.s.save_page(Page(dt.date(2026, 11, day), todo=[f"{day}일"]))
        self.s.save_page(Page(dt.date(2026, 12, 5), todo=["12월"]))
        self.assertEqual(self.s.page_count(), 4)
        self.assertEqual(self.s.page_count(dt.date(2026, 11, 1), dt.date(2026, 11, 30)), 3)
        self.assertEqual(self.s.page_count(dt.date(2026, 11, 10), dt.date(2026, 11, 10)), 1)
        self.assertEqual(self.s.date_range(), (dt.date(2026, 11, 1), dt.date(2026, 12, 5)))
        out = self.dir / "nov.json"
        self.assertEqual(self.s.export_json(out, dt.date(2026, 11, 5), dt.date(2026, 11, 30)), 2)
        dates = [p["date"] for p in json.loads(out.read_text(encoding="utf-8"))["pages"]]
        self.assertEqual(dates, ["2026-11-10", "2026-11-20"])
        txt = self.dir / "nov.txt"
        self.assertEqual(self.s.export_text(txt, dt.date(2026, 12, 1), None), 1)
        self.assertIn("2026-12-05", txt.read_text(encoding="utf-8"))
        empty = Storage(self.dir / "e.db")
        self.assertIsNone(empty.date_range())
        self.assertIsNone(empty.backup())          # 내용 없으면 백업 안 만듦
        empty.close()

    def test_dry_run_and_settings_import(self):
        self.s.save_page(sample_page())
        self.s.save_layout(PageLayout(schedule_lines=7, line_height=34))
        self.s.set_setting("font_family", "바탕")
        out = self.dir / "all.json"
        self.s.export_json(out)
        other = Storage(self.dir / "o.db")
        r = other.import_json(out, dry_run=True, take_settings=True)
        self.assertEqual((r.added, r.updated, r.skipped), (1, 0, 0))
        self.assertEqual(other.page_count(), 0)                    # 미리보기는 아무것도 안 바꿈
        self.assertEqual(other.load_layout(), PageLayout())
        other.import_json(out)                                     # 설정 빼고
        self.assertEqual(other.load_layout(), PageLayout())
        self.assertIsNone(other.get_setting("font_family"))
        other.import_json(out, take_settings=True)
        self.assertEqual(other.load_layout().schedule_lines, 7)
        self.assertEqual(other.get_setting("font_family"), "바탕")
        other.close()

    def test_auto_backup_keeps_recent(self):
        self.s.save_page(sample_page())
        made = []
        for i in range(4):
            self.clock.t = f"2026-11-10T09:00:0{i}"
            made.append(self.s.backup(keep=3))
        again = self.s.backup(keep=3)                              # 같은 초에 또: 덮어쓰지 않음
        self.assertNotEqual(again, made[-1])
        files = sorted(f.name for f in (self.dir / "a" / "backups").iterdir())
        self.assertEqual(len(files), 3)
        self.assertIn(again.name, files)
        restored = Storage(self.dir / "r.db")
        self.assertEqual(restored.import_json(again).added, 1)     # 백업 파일은 그대로 가져오기 가능
        restored.close()

    def test_import_rejects_other_files(self):
        bad = self.dir / "x.json"
        bad.write_text('{"format": "something"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.s.import_json(bad)
        bad.write_text('[1, 2]', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.s.import_json(bad)

    def test_text_export(self):
        txt = pages_to_text([sample_page()])
        self.assertIn("==== 2026-11-10 (화) ====", txt)
        self.assertIn("  [09:12] | 아침 회의 정리", txt)
        self.assertIn("          | 이어서 쓴 줄", txt)
        self.assertIn("  - 서류 검토", txt)
        n = self.s.export_text(self.dir / "out.txt")
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
