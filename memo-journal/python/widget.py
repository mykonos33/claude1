"""바탕화면 캘린더 위젯 (3단계).

어두운 반투명 둥근 창. 왼쪽은 영구 캘린더, 오른쪽은 고른 날짜의 일정 개요.
    - 휠 / ‹ › : 달 이동,  달 제목 클릭: 오늘로
    - 날짜 클릭: 그 날 일정 보기,  더블클릭: 그 날 속지 열기
    - 아무 데나 끌기: 위치 옮기기(기억함),  Ctrl+휠: 크기
    - 오른쪽 클릭: 메뉴
창 테두리 없음, 작업표시줄에 안 뜸, 항상 다른 창 아래(바탕화면 쪽)에 깔림.
"""
from __future__ import annotations

import datetime as dt
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QWidget

from calendar_core import WEEKDAY_NAMES, month_grid, shift_month, sunday_index
from storage import Storage
from timestamp import format_item_time

FONT_FAMILIES = ["Malgun Gothic", "맑은 고딕", "Apple SD Gothic Neo", "Noto Sans CJK KR", "NanumGothic", "Sans Serif"]

# 기준 크기(배율 1.0일 때 픽셀)
W, H = 600, 330
PAD = 26
COL, ROW = 40, 36            # 날짜 칸
GRID_TOP = 97                # 첫 주 칸의 위쪽
PANEL_X = PAD + 7 * COL + 30  # 오른쪽 일정 개요 시작
ITEM_TOP, ITEM_PITCH = 70, 52
MAX_ROWS = (H - ITEM_TOP - 10) // ITEM_PITCH
SCALE_MIN, SCALE_MAX = 0.7, 1.8

C = {
    "bg": QColor(28, 29, 33, 238),
    "text": QColor("#f3f3f4"),
    "dim": QColor("#63666d"),
    "sub": QColor("#a9acb3"),
    "sun": QColor("#ff6b6b"),
    "sat": QColor("#5aa2f5"),
    "today": QColor("#2d7ff0"),
    "ring": QColor("#8d9097"),
    "bar": QColor("#3f7fe8"),
    "bar_dim": QColor("#6b6e76"),
    "dot": QColor("#8d9097"),
}


def make_app_icon(size: int = 64) -> QIcon:
    """트레이/창 아이콘(그림 파일 없이 직접 그림)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 64, size / 64)  # 아래 좌표는 64x64 기준
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#2b2d31"))
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setBrush(QColor("#2d7ff0"))
    p.drawRoundedRect(2, 2, 60, 20, 14, 14)
    p.drawRect(2, 12, 60, 10)
    p.setBrush(QColor("#f3f3f4"))
    for r in range(2):
        for c in range(3):
            p.drawRoundedRect(13 + c * 14, 30 + r * 13, 9, 8, 2, 2)
    p.end()
    return QIcon(pm)


class CalendarWidget(QWidget):
    openRequested = Signal(object)  # 열 날짜(dt.date)
    hideRequested = Signal()
    quitRequested = Signal()

    def __init__(self, storage: Storage, clock: Callable[[], dt.datetime] = dt.datetime.now,
                 font_family: str = FONT_FAMILIES[0]):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnBottomHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("메모+일지 캘린더")
        self.storage = storage
        self.clock = clock
        self.font_family = font_family
        self.can_hide = True  # 트레이가 없으면 숨기기 메뉴를 빼야 함(다시 꺼낼 방법이 없으므로)
        try:
            self.scale = float(storage.get_setting("widget_scale", "1.0"))
        except ValueError:
            self.scale = 1.0
        self.scale = max(SCALE_MIN, min(SCALE_MAX, self.scale))

        self.today = clock().date()
        self.selected = self.today
        self.year, self.month = self.today.year, self.today.month
        self._press: Optional[QPoint] = None
        self._origin = QPoint()
        self._dragging = False
        self.dots: dict[dt.date, bool] = {}   # 날짜 → 일정이 있는지(False면 일지/할 일만)
        self.header = ""
        self.rows: list[tuple[str, str, bool]] = []  # (제목, 시각 문구, 고른 날의 일정인지)
        self.no_items = False

        self.setFixedSize(self.s(W), self.s(H))
        self._restore_position()
        self.refresh()

        self.timer = QTimer(self)
        self.timer.setInterval(30_000)
        self.timer.timeout.connect(self.check_day_change)
        self.timer.start()

    # ---------- 크기 / 글꼴 ----------
    def s(self, v: float) -> int:
        return round(v * self.scale)

    def font_(self, px: int, bold: bool = False) -> QFont:
        f = QFont()
        f.setFamilies([self.font_family] + [x for x in FONT_FAMILIES if x != self.font_family])
        f.setPixelSize(max(8, self.s(px)))
        f.setBold(bold)
        return f

    def set_font_family(self, family: str) -> None:
        self.font_family = family
        self.update()

    def set_scale(self, scale: float) -> None:
        self.scale = round(max(SCALE_MIN, min(SCALE_MAX, scale)), 2)
        self.setFixedSize(self.s(W), self.s(H))
        self.storage.set_setting("widget_scale", str(self.scale))
        self.update()

    # ---------- 위치 ----------
    def _restore_position(self) -> None:
        raw = self.storage.get_setting("widget_pos", "")
        try:
            x, y = (int(v) for v in raw.split(","))
            pos: Optional[QPoint] = QPoint(x, y)
        except ValueError:
            pos = None
        screens = QGuiApplication.screens()
        if pos is not None and not any(sc.availableGeometry().intersects(QRect(pos, self.size())) for sc in screens):
            pos = None  # 모니터 구성이 바뀌어 화면 밖이면 기본 위치로
        if pos is None and screens:
            g = QGuiApplication.primaryScreen().availableGeometry()
            pos = QPoint(g.right() - self.width() - 40, g.top() + 40)
        if pos is not None:
            self.move(pos)

    # ---------- 자료 ----------
    def refresh(self) -> None:
        """저장 내용이 바뀌었거나 달/날짜를 옮겼을 때 다시 읽기."""
        self.dots = {}
        with_schedule = set()
        months = {(self.year, self.month), shift_month(self.year, self.month, -1), shift_month(self.year, self.month, 1)}
        for y, m in months:
            for d in self.storage.dates_with_content(y, m):
                self.dots[d] = False
            with_schedule |= self.storage.dates_with_schedule(y, m)
        for d in with_schedule:
            self.dots[d] = True

        d = self.selected
        label = f"{d.month}월 {d.day}일 ({WEEKDAY_NAMES[sunday_index(d)]})"
        self.header = f"오늘 · {label}" if d == self.today else label
        items = self.storage.get_page(d).schedule_items()
        self.no_items = not items
        if items:
            self.rows = [(it.title, format_item_time(it), True) for it in items]
        else:
            self.rows = [
                (it.title, f"{u.month}/{u.day} ({WEEKDAY_NAMES[sunday_index(u)]}) {format_item_time(it)}", False)
                for u, it in self.storage.upcoming(d + dt.timedelta(days=1), limit=MAX_ROWS)
            ]
        self.update()

    def check_day_change(self) -> None:
        """자정이 지나면 '오늘' 표시를 옮긴다(보고 있던 것이 오늘이면 같이 따라감)."""
        now = self.clock().date()
        if now == self.today:
            return
        was_today = self.selected == self.today
        was_this_month = (self.year, self.month) == (self.today.year, self.today.month)
        self.today = now
        if was_today:
            self.selected = now
        if was_this_month:
            self.year, self.month = now.year, now.month
        self.refresh()

    def go_month(self, delta: int) -> None:
        try:
            self.year, self.month = shift_month(self.year, self.month, delta)
        except ValueError:
            return
        self.refresh()

    def go_today(self) -> None:
        self.selected = self.today
        self.year, self.month = self.today.year, self.today.month
        self.refresh()

    def select(self, date: dt.date) -> None:
        self.selected = date
        self.year, self.month = date.year, date.month  # 흐린 이전/다음 달 날짜를 누르면 그 달로
        self.refresh()

    # ---------- 자리 계산 ----------
    def weeks(self):
        return month_grid(self.year, self.month)

    def cell_rect(self, row: int, col: int) -> QRect:
        return QRect(self.s(PAD) + col * self.s(COL), self.s(GRID_TOP) + row * self.s(ROW), self.s(COL), self.s(ROW))

    def date_rect(self, date: dt.date) -> Optional[QRect]:
        for r, week in enumerate(self.weeks()):
            for c, day in enumerate(week):
                if day.date == date:
                    return self.cell_rect(r, c)
        return None

    def date_at(self, pos: QPoint) -> Optional[dt.date]:
        for r, week in enumerate(self.weeks()):
            for c, day in enumerate(week):
                if self.cell_rect(r, c).contains(pos):
                    return day.date
        return None

    def title_rect(self) -> QRect:
        return QRect(self.s(PAD), self.s(24), self.s(150), self.s(38))

    def arrow_rects(self) -> dict[int, QRect]:
        right = self.s(PAD + 7 * COL)
        return {-1: QRect(right - self.s(64), self.s(28), self.s(30), self.s(30)),
                1: QRect(right - self.s(32), self.s(28), self.s(30), self.s(30))}

    def panel_rect(self) -> QRect:
        return QRect(self.s(PANEL_X), 0, self.width() - self.s(PANEL_X), self.height())

    # ---------- 그리기 ----------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.s
        p.setPen(Qt.NoPen)
        p.setBrush(C["bg"])
        p.drawRoundedRect(self.rect(), s(22), s(22))

        # 달 제목 + 연도
        title_font = self.font_(23, bold=True)
        p.setFont(title_font)
        p.setPen(C["text"])
        title = f"{self.month}월"
        p.drawText(s(PAD + 8), s(53), title)
        tw = QFontMetrics(title_font).horizontalAdvance(title)
        p.setFont(self.font_(13))
        p.setPen(C["sub"])
        p.drawText(s(PAD + 8) + tw + s(8), s(53), str(self.year))
        p.setFont(self.font_(22))
        for delta, rect in self.arrow_rects().items():
            p.drawText(rect, Qt.AlignCenter, "‹" if delta < 0 else "›")

        # 요일 줄
        p.setFont(self.font_(14))
        for c, ch in enumerate(WEEKDAY_NAMES):
            p.setPen(C["sun"] if c == 0 else C["sat"] if c == 6 else C["ring"])
            p.drawText(QRect(s(PAD) + c * s(COL), s(66), s(COL), s(28)), Qt.AlignCenter, ch)

        # 날짜
        num_font, num_bold = self.font_(15), self.font_(15, bold=True)
        d_circle = s(29)
        for r, week in enumerate(self.weeks()):
            for c, day in enumerate(week):
                rect = self.cell_rect(r, c)
                cx, cy = rect.center().x() + 1, rect.top() + s(17)
                circle = QRectF(cx - d_circle / 2, cy - d_circle / 2, d_circle, d_circle)
                is_today = day.date == self.today
                if is_today:
                    p.setPen(Qt.NoPen)
                    p.setBrush(C["today"])
                    p.drawEllipse(circle)
                elif day.date == self.selected:
                    p.setPen(QPen(C["ring"], max(1.0, self.scale * 1.4)))
                    p.setBrush(Qt.NoBrush)
                    p.drawEllipse(circle)
                if is_today:
                    color = QColor("#ffffff")
                elif not day.in_month:
                    color = C["dim"]
                else:
                    color = {"sun": C["sun"], "sat": C["sat"]}.get(day.kind, C["text"])
                p.setFont(num_bold if day.in_month else num_font)
                p.setPen(color)
                p.drawText(circle, Qt.AlignCenter, str(day.date.day))
                if day.date in self.dots:
                    p.setPen(Qt.NoPen)
                    dot = QColor(C["bar"] if self.dots[day.date] else C["dot"])
                    if not day.in_month:
                        dot.setAlpha(110)
                    p.setBrush(dot)
                    rad = max(1.5, self.scale * 2.0)
                    p.drawEllipse(QRectF(cx - rad, rect.bottom() - rad * 2 + 1, rad * 2, rad * 2))

        # 오른쪽: 일정 개요
        x0, width = s(PANEL_X), self.width() - s(PANEL_X) - s(PAD)
        p.setFont(self.font_(13))
        p.setPen(C["sub"])
        p.drawText(x0, s(52), self.header)
        y = s(ITEM_TOP)
        if self.no_items:
            p.drawText(x0, y + s(16), "일정 없음")
            y += s(34)
            if self.rows:
                p.setFont(self.font_(12))
                p.setPen(C["ring"])
                p.drawText(x0, y + s(8), "다가오는 일정")
                y += s(20)
        room = max(1, (self.height() - y - s(10)) // s(ITEM_PITCH))
        shown = self.rows if len(self.rows) <= room else self.rows[: room - 1]
        title_f, time_f = self.font_(15, bold=True), self.font_(13)
        for title, when, mine in shown:
            p.setPen(Qt.NoPen)
            p.setBrush(C["bar"] if mine else C["bar_dim"])
            p.drawRoundedRect(QRectF(x0, y, s(4), s(42)), s(2), s(2))
            p.setFont(title_f)
            p.setPen(C["text"])
            p.drawText(x0 + s(14), y + s(17), QFontMetrics(title_f).elidedText(title, Qt.ElideRight, width - s(14)))
            p.setFont(time_f)
            p.setPen(C["sub"])
            p.drawText(x0 + s(14), y + s(37), QFontMetrics(time_f).elidedText(when, Qt.ElideRight, width - s(14)))
            y += s(ITEM_PITCH)
        if len(shown) < len(self.rows):
            p.setFont(self.font_(13))
            p.setPen(C["sub"])
            p.drawText(x0 + s(14), y + s(18), f"+{len(self.rows) - len(shown)}개 더")

    # ---------- 마우스 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.globalPosition().toPoint()
            self._origin = self.pos()
            self._dragging = False

    def mouseMoveEvent(self, e):
        if self._press is None:
            return
        delta = e.globalPosition().toPoint() - self._press
        if self._dragging or delta.manhattanLength() > 5:
            self._dragging = True
            self.move(self._origin + delta)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._press is None:
            return
        self._press = None
        if self._dragging:
            self._dragging = False
            self.storage.set_setting("widget_pos", f"{self.x()},{self.y()}")
        else:
            self.click(e.position().toPoint())

    def click(self, pos: QPoint) -> None:
        for delta, rect in self.arrow_rects().items():
            if rect.contains(pos):
                self.go_month(delta)
                return
        if self.title_rect().contains(pos):
            self.go_today()
            return
        date = self.date_at(pos)
        if date is not None:
            self.select(date)

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = e.position().toPoint()
        date = self.date_at(pos)
        if date is not None:
            self.select(date)
            self.openRequested.emit(date)
        elif self.panel_rect().contains(pos):
            self.openRequested.emit(self.selected)

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        if not dy:
            return
        if e.modifiers() & Qt.ControlModifier:
            self.set_scale(self.scale + (0.1 if dy > 0 else -0.1))
        else:
            self.go_month(-1 if dy > 0 else 1)
        e.accept()

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        d = self.selected
        menu.addAction(f"{d.month}월 {d.day}일 속지 열기", lambda: self.openRequested.emit(self.selected))
        menu.addAction("오늘로", self.go_today)
        menu.addSeparator()
        menu.addAction("크게", lambda: self.set_scale(self.scale + 0.1))
        menu.addAction("작게", lambda: self.set_scale(self.scale - 0.1))
        menu.addSeparator()
        if self.can_hide:
            menu.addAction("위젯 숨기기", self.hideRequested.emit)
        menu.addAction("프로그램 종료", self.quitRequested.emit)
        menu.exec(e.globalPos())
