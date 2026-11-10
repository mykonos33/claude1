"""저장/불러오기/내보내기 (GUI 없음).

날짜 하나 = 속지 한 장(Page). SQLite 파일 하나에 저장한다.
C++/러스트 버전도 같은 DB 구조와 같은 JSON 규격을 쓴다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from calendar_core import date_label
from layout import PageLayout
from timestamp import ScheduleItem, parse_schedule

FORMAT_NAME = "memo-journal"
FORMAT_VERSION = 1
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    date     TEXT PRIMARY KEY,   -- '2026-11-10'
    schedule TEXT NOT NULL DEFAULT '',   -- 일정 줄들('\\n' 구분)
    journal  TEXT NOT NULL DEFAULT '[]', -- JSON [{"cue": "[09:12]", "text": "..."}]
    todo     TEXT NOT NULL DEFAULT '',   -- 내일 할 일 줄들('\\n' 구분)
    updated  TEXT NOT NULL,              -- '2026-11-10T21:03:11'
    fmt      TEXT NOT NULL DEFAULT '{}'  -- 굵게/밑줄 JSON {"journal": [[줄, 시작, 길이, "b"|"u"], ...]}
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class Entry:
    """일지 한 문단: 왼쪽 개요 칸(cue, 편집 가능한 텍스트) + 오른쪽 본문."""

    cue: str = ""
    text: str = ""

    def is_empty(self) -> bool:
        return not self.cue.strip() and not self.text.strip()


STYLES = ("b", "u")  # 굵게, 밑줄
FMT_SECTIONS = ("schedule", "journal", "todo")


def clean_fmt(fmt: object, line_counts: dict[str, int]) -> dict[str, list[list]]:
    """굵게/밑줄 표시 정리. 위치는 줄(일지는 문단) 번호와 그 줄 안의 글자 위치(유니코드 글자 단위).

    잘못된 값과 없는 줄을 가리키는 표시는 버린다. 표시가 없는 구역은 키를 넣지 않는다.
    """
    out: dict[str, list[list]] = {}
    if not isinstance(fmt, dict):
        return out
    for sec in FMT_SECTIONS:
        marks = []
        for m in fmt.get(sec) or []:
            try:
                line, start, length, style = int(m[0]), int(m[1]), int(m[2]), str(m[3])
            except (TypeError, ValueError, IndexError):
                continue
            if style in STYLES and 0 <= line < line_counts.get(sec, 0) and start >= 0 and length > 0:
                marks.append([line, start, length, style])
        if marks:
            out[sec] = sorted(marks)
    return out


@dataclass
class Page:
    date: dt.date
    schedule: list[str] = field(default_factory=list)
    journal: list[Entry] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    updated: str = ""
    fmt: dict[str, list[list]] = field(default_factory=dict)  # 굵게/밑줄(clean_fmt 참고)

    def is_empty(self) -> bool:
        return (
            not any(l.strip() for l in self.schedule)
            and all(e.is_empty() for e in self.journal)
            and not any(l.strip() for l in self.todo)
        )

    def schedule_items(self) -> list[ScheduleItem]:
        return parse_schedule(self.schedule)

    # --- JSON 규격 ---
    def to_json(self) -> dict:
        schedule, journal, todo = _trim(self.schedule), _trim_entries(self.journal), _trim(self.todo)
        d = {
            "date": self.date.isoformat(),
            "schedule": schedule,
            "journal": [{"cue": e.cue, "text": e.text} for e in journal],
            "todo": todo,
            "updated": self.updated,
        }
        fmt = clean_fmt(self.fmt, {"schedule": len(schedule), "journal": len(journal), "todo": len(todo)})
        if fmt:
            d["fmt"] = fmt
        return d

    @classmethod
    def from_json(cls, d: dict) -> "Page":
        return cls(
            date=dt.date.fromisoformat(d["date"]),
            schedule=[str(x) for x in d.get("schedule", [])],
            journal=[Entry(str(e.get("cue", "")), str(e.get("text", ""))) for e in d.get("journal", [])],
            todo=[str(x) for x in d.get("todo", [])],
            updated=str(d.get("updated", "")),
            fmt=d.get("fmt") if isinstance(d.get("fmt"), dict) else {},
        )


def _trim(lines: list[str]) -> list[str]:
    """끝쪽 빈 줄 제거(중간 빈 줄은 사용자가 띄운 것이므로 유지)."""
    out = list(lines)
    while out and not out[-1].strip():
        out.pop()
    return out


def _trim_entries(entries: list[Entry]) -> list[Entry]:
    out = list(entries)
    while out and out[-1].is_empty():
        out.pop()
    return out


def default_db_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "MemoJournal"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "MemoJournal"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "memo-journal"
    return base / "journal.db"


def _now_iso() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


@dataclass
class ImportResult:
    added: int = 0
    updated: int = 0
    skipped: int = 0  # 이쪽이 같거나 더 최신이라 건너뜀


class Storage:
    def __init__(self, path: str | Path, clock: Callable[[], str] = _now_iso):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.db = sqlite3.connect(str(path))
        self.db.executescript(_SCHEMA)
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(pages)")}
        if "fmt" not in cols:  # 굵게/밑줄 이전에 만든 저장 파일
            self.db.execute("ALTER TABLE pages ADD COLUMN fmt TEXT NOT NULL DEFAULT '{}'")
        self.db.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),)
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # --- 속지 ---
    def get_page(self, date: dt.date) -> Page:
        row = self.db.execute(
            "SELECT schedule, journal, todo, updated, fmt FROM pages WHERE date = ?", (date.isoformat(),)
        ).fetchone()
        if not row:
            return Page(date)
        schedule, journal, todo, updated, fmt = row
        try:
            fmt = json.loads(fmt or "{}")
        except json.JSONDecodeError:
            fmt = {}
        return Page(
            date=date,
            schedule=schedule.split("\n") if schedule else [],
            journal=[Entry(e.get("cue", ""), e.get("text", "")) for e in json.loads(journal or "[]")],
            todo=todo.split("\n") if todo else [],
            updated=updated,
            fmt=fmt if isinstance(fmt, dict) else {},
        )

    def save_page(self, page: Page, *, keep_updated: bool = False) -> None:
        """저장. 내용이 모두 비면 행을 지운다(달력에 점이 안 찍히도록)."""
        if page.is_empty():
            self.db.execute("DELETE FROM pages WHERE date = ?", (page.date.isoformat(),))
            self.db.commit()
            return
        if not keep_updated or not page.updated:
            page.updated = self.clock()
        d = page.to_json()
        self.db.execute(
            "INSERT INTO pages(date, schedule, journal, todo, updated, fmt) VALUES(?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(date) DO UPDATE SET schedule=excluded.schedule, journal=excluded.journal, "
            "todo=excluded.todo, updated=excluded.updated, fmt=excluded.fmt",
            (
                d["date"],
                "\n".join(d["schedule"]),
                json.dumps(d["journal"], ensure_ascii=False),
                "\n".join(d["todo"]),
                d["updated"],
                json.dumps(d.get("fmt", {}), ensure_ascii=False),
            ),
        )
        self.db.commit()

    def dates_with_content(self, year: int, month: int) -> set[dt.date]:
        """달력에 점을 찍을 날짜들."""
        prefix = f"{year:04d}-{month:02d}-%"
        rows = self.db.execute("SELECT date FROM pages WHERE date LIKE ?", (prefix,))
        return {dt.date.fromisoformat(r[0]) for r in rows}

    def dates_with_schedule(self, year: int, month: int) -> set[dt.date]:
        prefix = f"{year:04d}-{month:02d}-%"
        rows = self.db.execute(
            "SELECT date, schedule FROM pages WHERE date LIKE ? AND schedule != ''", (prefix,)
        )
        return {dt.date.fromisoformat(d) for d, s in rows if s.strip()}

    def upcoming(self, start: dt.date, limit: int = 3) -> list[tuple[dt.date, ScheduleItem]]:
        """start 날짜부터 다가오는 일정(위젯 개요가 비었을 때 사용)."""
        out: list[tuple[dt.date, ScheduleItem]] = []
        rows = self.db.execute(
            "SELECT date, schedule FROM pages WHERE date >= ? AND schedule != '' ORDER BY date",
            (start.isoformat(),),
        )
        for d, s in rows:
            for item in parse_schedule(s.split("\n")):
                out.append((dt.date.fromisoformat(d), item))
                if len(out) >= limit:
                    return out
        return out

    def previous_todo(self, date: dt.date) -> list[str]:
        """date 이전에 가장 가까운 날의 '내일 할 일'(새 속지를 열 때 참고용)."""
        row = self.db.execute(
            "SELECT todo FROM pages WHERE date < ? AND todo != '' ORDER BY date DESC LIMIT 1",
            (date.isoformat(),),
        ).fetchone()
        return row[0].split("\n") if row else []

    def all_pages(self, start: Optional[dt.date] = None, end: Optional[dt.date] = None) -> list[Page]:
        rows = self.db.execute("SELECT date FROM pages ORDER BY date").fetchall()
        pages = []
        for (d,) in rows:
            day = dt.date.fromisoformat(d)
            if (start and day < start) or (end and day > end):
                continue
            pages.append(self.get_page(day))
        return pages

    # --- 설정 ---
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.db.commit()

    def load_layout(self) -> PageLayout:
        raw = self.get_setting("page_layout")
        try:
            return PageLayout.from_dict(json.loads(raw) if raw else None)
        except json.JSONDecodeError:
            return PageLayout()

    def save_layout(self, layout: PageLayout) -> None:
        self.set_setting("page_layout", json.dumps(layout.to_dict()))

    # --- 내보내기 / 가져오기 ---
    def export_json(self, path: str | Path, start: Optional[dt.date] = None, end: Optional[dt.date] = None) -> int:
        pages = self.all_pages(start, end)
        data = {
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            "exported": self.clock(),
            "layout": self.load_layout().to_dict(),
            "pages": [p.to_json() for p in pages],
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(pages)

    def import_json(self, path: str | Path, *, take_layout: bool = False) -> ImportResult:
        """다른 PC에서 내보낸 JSON 합치기. 같은 날짜면 updated가 더 최신인 쪽을 남긴다."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("format") != FORMAT_NAME:
            raise ValueError("메모+일지 내보내기 파일이 아닙니다")
        if int(data.get("version", 0)) > FORMAT_VERSION:
            raise ValueError("더 새 버전 앱에서 만든 파일입니다. 앱을 업데이트해 주세요")
        result = ImportResult()
        for raw in data.get("pages", []):
            incoming = Page.from_json(raw)
            if incoming.is_empty():
                continue
            current = self.get_page(incoming.date)
            if current.is_empty():
                result.added += 1
            elif incoming.updated > current.updated:
                result.updated += 1
            else:
                result.skipped += 1
                continue
            self.save_page(incoming, keep_updated=True)
        if take_layout and data.get("layout"):
            self.save_layout(PageLayout.from_dict(data["layout"]))
        return result

    def export_text(self, path: str | Path, start: Optional[dt.date] = None, end: Optional[dt.date] = None) -> int:
        pages = self.all_pages(start, end)
        Path(path).write_text(pages_to_text(pages), encoding="utf-8")
        return len(pages)


def pages_to_text(pages: Iterable[Page]) -> str:
    """사람이 읽는 TXT. 코넬 칸 구조를 '개요 | 본문'으로 표현."""
    blocks = []
    for p in pages:
        lines = [f"==== {date_label(p.date)} ===="]
        sched = _trim(p.schedule)
        if sched:
            lines.append("[일정]")
            lines += [f"  {l}" for l in sched]
        entries = _trim_entries(p.journal)
        if entries:
            lines.append("[일지]")
            width = max(len(e.cue) for e in entries)
            for e in entries:
                lines.append(f"  {e.cue.ljust(width)} | {e.text}".rstrip())
        todo = _trim(p.todo)
        if todo:
            lines.append("[내일 할 일]")
            lines += [f"  - {l}" if l.strip() else "" for l in todo]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")
