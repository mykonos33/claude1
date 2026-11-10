"""타임스탬프와 일정 줄 해석 규칙 (GUI 없음).

- 일지의 타임스탬프는 왼쪽(개요) 칸에 들어가는 '편집 가능한 일반 텍스트'다.
  앱은 비어 있는 개요 칸에 기본값 `[HH:MM]`을 넣어 줄 뿐, 사용자가 자유롭게 고칠 수 있다.
- 일정 칸은 자유 텍스트 줄이다. 줄 앞에 시각이 있으면 위젯 개요에 시각과 함께 표시한다.
  예) `21:00~22:00 새 일정`, `[09:30] 회의`, `14:00-15:30 면담`, `시각 없는 일정`
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Optional

_TIME = r"(\d{1,2})\s*:\s*(\d{2})"
_STAMP_RE = re.compile(r"^\s*\[?\s*" + _TIME + r"\s*\]?\s*$")
_SCHEDULE_RE = re.compile(
    r"^\s*\[?\s*" + _TIME + r"(?:\s*[~\-–]\s*" + _TIME + r")?\s*\]?\s*(.*)$"
)


def format_stamp(now: dt.datetime | dt.time) -> str:
    """현재 시각 → '[21:05]' (24시간제)."""
    return f"[{now.hour:02d}:{now.minute:02d}]"


def _valid(h: int, m: int) -> bool:
    return 0 <= h <= 23 and 0 <= m <= 59


def parse_stamp(text: str) -> Optional[str]:
    """개요 칸 텍스트에서 시각을 읽어 'HH:MM'으로. 시각 형식이 아니면 None.

    사용자가 '업무 후' 같은 글자를 적어 구분 표시로 써도 되도록, 실패해도 오류는 내지 않는다.
    """
    m = _STAMP_RE.match(text or "")
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return f"{h:02d}:{mi:02d}" if _valid(h, mi) else None


def needs_stamp(cue: str, old_text: str, new_text: str) -> bool:
    """본문을 새로 쓰기 시작한 순간에만 타임스탬프를 넣는다.

    - 개요 칸이 비어 있고
    - 본문이 비어 있다가 글자가 생겼을 때
    사용자가 개요 칸을 지웠거나 고친 줄은, 본문이 비어 있지 않으면 다시 채우지 않는다.
    """
    return not (cue or "").strip() and not (old_text or "").strip() and bool((new_text or "").strip())


@dataclass(frozen=True)
class ScheduleItem:
    start: Optional[str]  # 'HH:MM' 또는 None(시각 없음)
    end: Optional[str]
    title: str

    def sort_key(self) -> tuple:
        # 시각 없는 일정은 맨 앞(종일 일정처럼)
        return (self.start is not None, self.start or "", self.end or "", self.title)


def parse_schedule_line(line: str) -> Optional[ScheduleItem]:
    """일정 칸 한 줄 해석. 빈 줄은 None."""
    if not line or not line.strip():
        return None
    m = _SCHEDULE_RE.match(line)
    if m:
        h1, m1 = int(m.group(1)), int(m.group(2))
        if _valid(h1, m1):
            start = f"{h1:02d}:{m1:02d}"
            end = None
            if m.group(3) is not None:
                h2, m2 = int(m.group(3)), int(m.group(4))
                if _valid(h2, m2):
                    end = f"{h2:02d}:{m2:02d}"
            title = m.group(5).strip() or "새 일정"
            return ScheduleItem(start, end, title)
    return ScheduleItem(None, None, line.strip())


def parse_schedule(lines: list[str]) -> list[ScheduleItem]:
    items = [it for it in (parse_schedule_line(l) for l in lines) if it]
    return sorted(items, key=ScheduleItem.sort_key)


def format_ampm(hhmm: str) -> str:
    """'21:00' → '오후 9:00', '00:30' → '오전 12:30', '12:00' → '오후 12:00'."""
    h, m = (int(x) for x in hhmm.split(":"))
    ampm = "오전" if h < 12 else "오후"
    h12 = h % 12 or 12
    return f"{ampm} {h12}:{m:02d}"


def format_item_time(item: ScheduleItem) -> str:
    """위젯 개요용 시각 문구. '오후 9:00 ~ 오후 10:00' / '오전 9:30' / '종일'."""
    if item.start is None:
        return "종일"
    if item.end is None:
        return format_ampm(item.start)
    return f"{format_ampm(item.start)} ~ {format_ampm(item.end)}"
