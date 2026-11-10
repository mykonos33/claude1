"""코넬 노트식 속지 배치 계산 (GUI 없음).

    ┌ Date. 2026-11-10 (화) ───────────────────┐
    │ 일정 (schedule_lines 줄, 전체 폭)           │
    ├──────────┬──────────────────────────────┤ ← 끌어서 일정 줄 수 조절
    │ 타임스탬프 │ 메인 일지 (journal_lines 줄)     │
    │ (cue_width)│                              │
    ├──────────┴──────────────────────────────┤ ← 끌어서 일지 줄 수 조절
    │ 내일 할 일 (todo_lines 줄)                  │
    └─────────────────────────────────────────┘ ← 끌어서 할 일 줄 수 조절

- 가로 경계선을 끌면 그 위 구역의 줄 수가 '한 줄 단위로' 늘거나 준다(아래 구역은 그대로 밀림).
- 세로선(개요 칸 오른쪽)을 끌면 개요 칸 폭이 바뀐다.
- Ctrl+휠은 줄 높이(확대/축소).
- 설정된 줄 수는 '최소 표시 줄 수'다. 내용이 더 많으면 그 구역은 자동으로 늘어난다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace

SECTIONS = ("schedule", "journal", "todo")
SECTION_TITLES = {"schedule": "일정", "journal": "일지", "todo": "내일 할 일"}

LIMITS = {
    "schedule_lines": (1, 30),
    "journal_lines": (1, 100),
    "todo_lines": (1, 30),
    "line_height": (18, 64),
    "cue_width": (48, 320),
}


def _clamp(name: str, value: int) -> int:
    lo, hi = LIMITS[name]
    return max(lo, min(hi, int(value)))


@dataclass(frozen=True)
class PageLayout:
    schedule_lines: int = 6
    journal_lines: int = 12
    todo_lines: int = 3
    line_height: int = 28  # px
    cue_width: int = 90  # px
    header_height: int = 36  # 'Date.' 머리줄 높이(px, 고정)

    def lines(self, section: str) -> int:
        return getattr(self, f"{section}_lines")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "PageLayout":
        base = cls()
        if not data:
            return base
        kwargs = {}
        for f in fields(cls):
            if f.name in data:
                try:
                    v = int(data[f.name])
                except (TypeError, ValueError):
                    continue
                kwargs[f.name] = _clamp(f.name, v) if f.name in LIMITS else v
        return replace(base, **kwargs)


def effective_lines(min_lines: int, used_lines: int) -> int:
    """실제로 그릴 줄 수: 설정 줄 수와 '내용 줄 수 + 빈 줄 1개' 중 큰 쪽."""
    return max(min_lines, used_lines + 1)


def section_bounds(layout: PageLayout, used: dict[str, int] | None = None) -> dict[str, tuple[int, int]]:
    """각 구역의 (위 y, 아래 y) 픽셀. used는 구역별 내용 줄 수(없으면 0)."""
    used = used or {}
    y = layout.header_height
    out = {}
    for s in SECTIONS:
        n = effective_lines(layout.lines(s), used.get(s, 0))
        out[s] = (y, y + n * layout.line_height)
        y += n * layout.line_height
    return out


def page_height(layout: PageLayout, used: dict[str, int] | None = None) -> int:
    return section_bounds(layout, used)["todo"][1]


def hit_divider(layout: PageLayout, y: int, used: dict[str, int] | None = None, grip: int = 4) -> str | None:
    """마우스 y가 어느 구역의 아래 경계선 위에 있는지. 없으면 None."""
    for s, (_, bottom) in section_bounds(layout, used).items():
        if abs(y - bottom) <= grip:
            return s
    return None


def resize_section(layout: PageLayout, section: str, delta_px: float) -> PageLayout:
    """구역 아래 경계선을 delta_px만큼 끌었을 때. 줄 단위로 맞춘다."""
    if section not in SECTIONS:
        raise ValueError(section)
    name = f"{section}_lines"
    steps = round(delta_px / layout.line_height)
    return replace(layout, **{name: _clamp(name, layout.lines(section) + steps)})


def resize_cue(layout: PageLayout, delta_px: float) -> PageLayout:
    return replace(layout, cue_width=_clamp("cue_width", layout.cue_width + delta_px))


def zoom(layout: PageLayout, steps: int) -> PageLayout:
    """Ctrl+휠 한 칸 = 2px. 개요 칸 폭도 같은 비율로 따라간다."""
    new_h = _clamp("line_height", layout.line_height + 2 * steps)
    ratio = new_h / layout.line_height
    return replace(layout, line_height=new_h, cue_width=_clamp("cue_width", round(layout.cue_width * ratio)))
