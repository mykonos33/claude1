"""영구 캘린더 계산 (GUI 없음).

위젯과 메인 창이 함께 쓰는 달력 격자, 요일 색, 달 이동 계산.
주는 일요일부터 시작한다(참고 위젯과 같음).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

WEEKDAY_NAMES = "일월화수목금토"  # 일요일 시작 순서


@dataclass(frozen=True)
class Day:
    date: dt.date
    in_month: bool  # False면 이전/다음 달 날짜(흐리게 표시)

    @property
    def kind(self) -> str:
        return day_kind(self.date)


def sunday_index(d: dt.date) -> int:
    """일요일=0 ... 토요일=6."""
    return (d.weekday() + 1) % 7


def day_kind(d: dt.date) -> str:
    """색 구분: 'sun'(빨강), 'sat'(파랑), 'weekday'."""
    i = sunday_index(d)
    if i == 0:
        return "sun"
    if i == 6:
        return "sat"
    return "weekday"


def month_grid(year: int, month: int) -> list[list[Day]]:
    """해당 달을 주 단위로 나눈 격자. 필요한 주 수만큼(4~6줄) 돌려준다."""
    first = dt.date(year, month, 1)
    start = first - dt.timedelta(days=sunday_index(first))
    ny, nm = shift_month(year, month, 1)
    last = dt.date(ny, nm, 1) - dt.timedelta(days=1)
    weeks: list[list[Day]] = []
    cur = start
    while cur <= last:
        week = []
        for _ in range(7):
            week.append(Day(cur, cur.month == month and cur.year == year))
            cur += dt.timedelta(days=1)
        weeks.append(week)
    return weeks


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """delta개월 앞/뒤로 이동. 연도 제한 없음(datetime 범위 1~9999년 안에서)."""
    idx = year * 12 + (month - 1) + delta
    y, m = divmod(idx, 12)
    if not 1 <= y <= 9999:
        raise ValueError("지원하는 연도는 1~9999년입니다")
    return y, m + 1


def date_label(d: dt.date) -> str:
    """'2026-11-10 (화)'"""
    return f"{d.isoformat()} ({WEEKDAY_NAMES[sunday_index(d)]})"


def month_label(year: int, month: int) -> str:
    return f"{year}년 {month}월"
