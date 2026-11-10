"""코넬 노트식 속지 편집 창 (2단계).

속지(Sheet) 한 장 = 날짜 하나. 날짜는 창 위쪽 막대에만 표시한다.
    일정    : 전체 폭 자유 텍스트 (왼쪽에 작은 '일정' 글씨)
    일지    : 왼쪽 개요 칸(타임스탬프, 편집 가능) | 오른쪽 본문  — 이름표 없음
    내일 할 일: 전체 폭 자유 텍스트 (왼쪽에 작은 '내일 할 일' 글씨)
가로 경계선을 끌면 줄 수, 세로선을 끌면 개요 칸 폭, Ctrl+휠은 확대/축소.
서식은 굵게(Ctrl+B)·밑줄(Ctrl+U)만. 글꼴은 글자별이 아니라 프로그램 전체에 하나.
"""
from __future__ import annotations

import datetime as dt
from typing import Callable, Optional

from PySide6.QtCore import QDate, QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction, QColor, QFont, QFontDatabase, QFontMetrics, QKeySequence, QPainter, QPen,
    QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocumentFragment,
)
from PySide6.QtWidgets import (
    QApplication, QCalendarWidget, QDialog, QDialogButtonBox, QFileDialog, QFontComboBox, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea,
    QTextEdit, QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

import layout as L
from calendar_core import date_label
from storage import Entry, Page, Storage
from timestamp import format_stamp, needs_stamp

COLORS = {
    "desk": "#d6d7d3",
    "paper": "#f7f6f1",
    "rule": "#cdd2d8",
    "border": "#3a3a3a",
    "cue_line": "#9aa3ad",
    "label": "#8b9096",
    "cue_text": "#2f64b0",
    "text": "#1f1f1f",
    "hint": "#aeb1b5",
}
FONT_FAMILIES = ["Malgun Gothic", "맑은 고딕", "Apple SD Gothic Neo", "Noto Sans CJK KR", "NanumGothic", "Sans Serif"]
TEXT_X_GAP = 10   # 개요 칸 오른쪽 선과 본문 사이
RIGHT_MARGIN = 14
BOTTOM_MARGIN = 28
SECTION_LABELS = {"schedule": "일정", "todo": "내일 할 일"}  # 가운데(일지)는 이름표 없음

_FIXED_HEIGHT = int(QTextBlockFormat.LineHeightTypes.FixedHeight.value)


DEFAULT_FONT = "Malgun Gothic"

SHORTCUTS = [  # (단축키, 설명) — 도움말 창과 메뉴에 같이 쓰임
    ("Ctrl+T", "타임스탬프 넣기 / 다시 누르면 빼기 (지금 문단의 왼쪽 칸)"),
    ("Ctrl+B", "굵게 켜기/끄기 (블록을 잡고 누르면 그 글자에 적용)"),
    ("Ctrl+U", "밑줄 켜기/끄기 (블록을 잡고 누르면 그 글자에 적용)"),
    ("Insert", "삽입 / 수정(겹쳐 쓰기) 전환"),
    ("Ctrl+PgUp", "전날로"),
    ("Ctrl+PgDown", "다음날로"),
    ("Ctrl+= / Ctrl+-", "크게 / 작게 (Ctrl+마우스 휠도 됨)"),
    ("Ctrl+Z / Ctrl+Y", "되돌리기 / 다시 하기"),
    ("Ctrl+W / Ctrl+Q", "창 닫기 / 프로그램 종료"),
    ("F1", "이 단축키 목록"),
]
MOUSE_HELP = [
    ("굵은 가로선 끌기", "그 위 구역의 줄 수 늘리기/줄이기"),
    ("점선 세로선 끌기", "타임스탬프 칸 폭 조절"),
    ("타임스탬프 칸에서 Enter", "그 문단 본문 끝으로 이동"),
]


def _u16(text: str) -> int:
    """Qt 글자 위치(UTF-16) 단위 길이."""
    return len(text.encode("utf-16-le")) // 2


def _u16_to_py(text: str, pos: int) -> int:
    acc = 0
    for i, ch in enumerate(text):
        if acc >= pos:
            return i
        acc += 2 if ord(ch) > 0xFFFF else 1
    return len(text)


def make_font(line_height: int, scale: float = 0.5, family: str = DEFAULT_FONT) -> QFont:
    f = QFont()
    f.setFamilies([family] + [x for x in FONT_FAMILIES if x != family])
    f.setPixelSize(max(9, round(line_height * scale)))
    return f


BOLD_MIN = 600  # 이 굵기 이상이면 '굵게'로 본다


class RuledEdit(QTextEdit):
    """투명 배경, 줄 높이 고정, 자체 스크롤 없음(높이는 속지가 정해 줌)."""

    insertPressed = Signal()  # Insert 키(삽입/수정 전환은 속지가 세 칸에 함께 적용)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setAcceptRichText(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setTabChangesFocus(True)
        self.setStyleSheet(f"QTextEdit {{ background: transparent; color: {COLORS['text']}; }}")
        self.viewport().setAutoFillBackground(False)
        self.document().setDocumentMargin(0)
        self.line_height = 28

    def apply_metrics(self, line_height: int, font: QFont) -> None:
        """글꼴과 고정 줄 높이를 모든 문단에 적용(되돌리기 기록은 비움)."""
        self.line_height = line_height
        self.setFont(font)
        doc = self.document()
        doc.setDefaultFont(font)
        doc.setUndoRedoEnabled(False)
        cur = QTextCursor(doc)
        cur.select(QTextCursor.Document)
        fmt = QTextBlockFormat()
        fmt.setLineHeight(line_height, _FIXED_HEIGHT)
        cur.mergeBlockFormat(fmt)
        doc.setUndoRedoEnabled(True)

    def insertFromMimeData(self, source) -> None:
        """붙여넣기는 서식 없이 글자만, 줄 높이는 유지."""
        text = source.text() if source.hasText() else ""
        if not text and source.hasHtml():
            text = QTextDocumentFragment.fromHtml(source.html()).toPlainText()
        if not text:
            return
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        cur = self.textCursor()
        cur.beginEditBlock()
        cur.insertText(text)
        whole = QTextCursor(self.document())
        whole.select(QTextCursor.Document)
        fmt = QTextBlockFormat()
        fmt.setLineHeight(self.line_height, _FIXED_HEIGHT)
        whole.mergeBlockFormat(fmt)
        cur.endEditBlock()
        self.setTextCursor(cur)

    def visual_lines(self) -> int:
        return max(1, round(self.document().size().height() / self.line_height))

    def wheelEvent(self, e):  # 휠은 속지(바깥 스크롤/확대)로 넘긴다
        e.ignore()

    def keyPressEvent(self, e):
        # Shift+Enter(문단 안 줄바꿈)도 보통 Enter로: 줄 = 문단으로 단순하게 유지
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and e.modifiers() & Qt.ShiftModifier:
            self.textCursor().insertBlock()
            return
        if e.key() == Qt.Key_Insert and e.modifiers() == Qt.NoModifier:
            self.insertPressed.emit()
            return
        super().keyPressEvent(e)

    def inputMethodEvent(self, e):
        """한글 입력기로 확정된 글자도 '수정' 모드에서는 뒤 글자를 덮어쓴다.
        (Qt 기본 겹쳐 쓰기는 키보드로 바로 들어오는 영문·숫자에만 적용됨)"""
        commit = e.commitString()
        over = self.overwriteMode() and bool(commit) and not self.textCursor().hasSelection()
        super().inputMethodEvent(e)
        if over:
            cur = self.textCursor()
            remaining = cur.block().length() - 1 - cur.positionInBlock()  # 문단 끝은 넘지 않음
            n = min(len(commit), remaining)
            if n > 0:
                cur.joinPreviousEditBlock()
                cur.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor, n)
                cur.removeSelectedText()
                cur.endEditBlock()

    def lines(self) -> list[str]:
        out, block = [], self.document().begin()
        while block.isValid():
            out.append(block.text().replace("\u2028", " "))
            block = block.next()
        return out

    # --- 굵게 / 밑줄 ---
    def _selection_all(self, pred) -> Optional[bool]:
        """블록으로 잡은 글자가 모두 pred를 만족하는지. 잡은 글자가 없으면 None."""
        cur = self.textCursor()
        if not cur.hasSelection():
            return None
        a, b = cur.selectionStart(), cur.selectionEnd()
        block, found = self.document().findBlock(a), False
        while block.isValid() and block.position() < b:
            base = block.position()
            for r in block.textFormats():
                if base + r.start + r.length <= a or base + r.start >= b:
                    continue
                found = True
                if not pred(r.format):
                    return False
            block = block.next()
        return True if found else None

    def is_bold(self) -> bool:
        """잡은 글자가 전부 굵으면 True(워드·한글 방식). 블록이 없으면 지금 입력 상태."""
        r = self._selection_all(lambda f: f.fontWeight() >= BOLD_MIN)
        return self.fontWeight() >= BOLD_MIN if r is None else r

    def is_underline(self) -> bool:
        r = self._selection_all(lambda f: f.fontUnderline())
        return self.fontUnderline() if r is None else r

    def toggle_bold(self) -> None:
        """하나라도 굵지 않으면 전체 굵게, 전부 굵을 때만 해제."""
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Normal if self.is_bold() else QFont.Bold)
        self.mergeCurrentCharFormat(fmt)

    def toggle_underline(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self.is_underline())
        self.mergeCurrentCharFormat(fmt)

    def marks(self) -> list[list]:
        """[[줄, 시작, 길이, 'b'|'u'], ...] — 위치는 파이썬 글자 단위."""
        out: list[list] = []
        block, line = self.document().begin(), 0
        while block.isValid():
            text = block.text()
            spans: dict[str, list[list[int]]] = {"b": [], "u": []}
            for r in block.textFormats():
                f = r.format
                a, b = _u16_to_py(text, r.start), _u16_to_py(text, r.start + r.length)
                if b <= a:
                    continue
                for style, on in (("b", f.fontWeight() >= BOLD_MIN), ("u", f.fontUnderline())):
                    if on:
                        sp = spans[style]
                        if sp and sp[-1][1] == a:  # 바로 이어지는 구간은 합친다
                            sp[-1][1] = b
                        else:
                            sp.append([a, b])
            for style, sp in spans.items():
                out += [[line, a, b - a, style] for a, b in sp]
            block, line = block.next(), line + 1
        return sorted(out)

    def apply_marks(self, marks: list[list]) -> None:
        doc = self.document()
        for line, start, length, style in marks:
            block = doc.findBlockByNumber(line)
            if not block.isValid():
                continue
            text = block.text()
            a = block.position() + _u16(text[:start])
            b = block.position() + _u16(text[: start + length])
            cur = QTextCursor(doc)
            cur.setPosition(a)
            cur.setPosition(b, QTextCursor.KeepAnchor)
            fmt = QTextCharFormat()
            if style == "b":
                fmt.setFontWeight(QFont.Bold)
            else:
                fmt.setFontUnderline(True)
            cur.mergeCharFormat(fmt)


class CueEdit(QLineEdit):
    """개요 칸 한 줄(타임스탬프). 보통 텍스트라 자유롭게 고칠 수 있다."""

    enterPressed = Signal(int)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.block_id = -1
        self.setFrame(False)
        self.setTextMargins(0, 0, 0, 0)
        self.setStyleSheet(f"QLineEdit {{ background: transparent; color: {COLORS['cue_text']}; }}")
        self.returnPressed.connect(lambda: self.enterPressed.emit(self.block_id))


class DragHandle(QWidget):
    """경계선 잡는 손잡이(보이지 않음, 마우스 모양만 바뀜)."""

    dragged = Signal(str, int)  # 이름, 누른 곳에서부터 이동한 픽셀
    released = Signal()

    def __init__(self, parent: QWidget, name: str, vertical: bool):
        super().__init__(parent)
        self.name = name
        self.vertical = vertical
        self.setCursor(Qt.SplitHCursor if vertical else Qt.SplitVCursor)
        self._start: Optional[QPoint] = None
        self.setToolTip("끌어서 개요 칸 폭 조절" if vertical else "끌어서 줄 수 조절")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._start = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if self._start is not None:
            d = e.globalPosition().toPoint() - self._start
            self.dragged.emit(self.name, d.x() if self.vertical else d.y())

    def mouseReleaseEvent(self, e):
        if self._start is not None:
            self._start = None
            self.released.emit()


class Sheet(QWidget):
    """코넬 속지 한 장."""

    edited = Signal()                 # 내용이 바뀜(자동 저장용)
    layoutCommitted = Signal(object)  # 끌기/확대가 끝남(설정 저장용)
    stateChanged = Signal()           # 굵게/밑줄/삽입·수정 표시를 다시 그려야 함

    def __init__(self, page_layout: L.PageLayout, clock: Callable[[], dt.datetime] = dt.datetime.now):
        super().__init__()
        self.lay = page_layout
        self.clock = clock
        self.font_family = DEFAULT_FONT
        self.overwrite = False                         # False=삽입, True=수정(겹쳐 쓰기)
        self.active_edit: Optional[RuledEdit] = None   # 지금 글을 쓰고 있는 칸
        self.schedule = RuledEdit(self)
        self.journal = RuledEdit(self)
        self.todo = RuledEdit(self)
        # 빈 칸 안내 문구(Qt 기본 안내 문구는 줄 위쪽에 떠서 직접 그린다)
        self.hints = {"schedule": "예) 21:00~22:00 회의", "journal": "", "todo": ""}
        self.edits = {"schedule": self.schedule, "journal": self.journal, "todo": self.todo}

        self.cues: dict[int, str] = {}       # 문단 번호 → 개요 칸 글
        self._prev_text: dict[int, str] = {}  # 문단 번호 → 직전 본문(자동 타임스탬프 판단용)
        self._next_id = 1
        self._cue_edits: list[CueEdit] = []
        self._loading = False
        self._relayout_pending = False
        self._drag_start_layout: Optional[L.PageLayout] = None

        self.handles = {s: DragHandle(self, s, False) for s in L.SECTIONS}
        self.handles["cue"] = DragHandle(self, "cue", True)
        for h in self.handles.values():
            h.dragged.connect(self._on_drag)
            h.released.connect(self._on_drag_end)

        self.journal.textChanged.connect(self._on_journal_changed)
        for e in self.edits.values():
            e.textChanged.connect(self._on_any_changed)
            e.document().documentLayout().documentSizeChanged.connect(lambda *_: self.request_relayout())
            e.cursorPositionChanged.connect(self._follow_cursor)
            e.cursorPositionChanged.connect(self.stateChanged)
            e.selectionChanged.connect(self.stateChanged)
            e.currentCharFormatChanged.connect(lambda *_: self.stateChanged.emit())
            e.insertPressed.connect(self.toggle_overwrite)
            e.installEventFilter(self)
        self._apply_metrics()

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.FocusIn and obj in self.edits.values():
            self.active_edit = obj
            self.stateChanged.emit()
        return super().eventFilter(obj, ev)

    def toggle_overwrite(self) -> None:
        self.set_overwrite(not self.overwrite)

    def set_overwrite(self, on: bool) -> None:
        self.overwrite = bool(on)
        for e in self.edits.values():
            e.setOverwriteMode(self.overwrite)
        self.stateChanged.emit()

    # ---------- 배치 ----------
    @property
    def edit_offset(self) -> int:
        """입력 칸의 위치 보정. Qt는 고정 줄 높이에서 글자를 줄 칸 아래쪽에 붙여 그려서
        (기준선 ≈ 줄 높이 - 글자 아래 길이) 보정 없이도 밑줄 바로 위에 앉는다."""
        return 0

    @property
    def baseline(self) -> int:
        """줄 칸 맨 위에서 본문 글자 기준선까지(개요 칸·이름표를 본문과 같은 높이에 맞출 때 사용)."""
        return self.lay.line_height - QFontMetrics(self.text_font).descent() - 2

    def _apply_metrics(self) -> None:
        lh = self.lay.line_height
        self.text_font = make_font(lh, 0.5, self.font_family)
        self.cue_font = make_font(lh, 0.46, self.font_family)
        self.label_font = make_font(lh, 0.4, self.font_family)
        for e in self.edits.values():
            e.apply_metrics(lh, self.text_font)
        for c in self._cue_edits:
            c.setFont(self.cue_font)

    def set_font_family(self, family: str) -> None:
        """프로그램 전체 글꼴(글자별 글꼴은 없음)."""
        self.font_family = family or DEFAULT_FONT
        self._apply_metrics()
        self.relayout()

    def set_layout(self, new: L.PageLayout) -> None:
        old = self.lay
        self.lay = new
        if new.line_height != old.line_height:
            self._apply_metrics()
        self.relayout()

    def used_lines(self) -> dict[str, int]:
        return {s: e.visual_lines() if e.toPlainText() else 0 for s, e in self.edits.items()}

    def request_relayout(self) -> None:
        if not self._relayout_pending:
            self._relayout_pending = True
            QTimer.singleShot(0, self.relayout)

    def relayout(self) -> None:
        self._relayout_pending = False
        lay, off, w = self.lay, self.edit_offset, self.width()
        bounds = L.section_bounds(lay, self.used_lines())
        x_text = lay.cue_width + TEXT_X_GAP
        for s, e in self.edits.items():
            top, bottom = bounds[s]
            e.setGeometry(x_text, top + off, max(50, w - x_text - RIGHT_MARGIN), bottom - top - off)
        for s in L.SECTIONS:
            self.handles[s].setGeometry(0, bounds[s][1] - 4, w, 8)
        jt, jb = bounds["journal"]
        self.handles["cue"].setGeometry(lay.cue_width - 4, jt + 4, 8, jb - jt - 8)
        self._place_cues(jt)
        self.setMinimumHeight(bounds["todo"][1] + BOTTOM_MARGIN)
        for h in self.handles.values():
            h.raise_()
        self.update()

    def _place_cues(self, section_top: int) -> None:
        doc = self.journal.document()
        dl = doc.documentLayout()
        block, i = doc.begin(), 0
        while block.isValid():
            if i == len(self._cue_edits):
                c = CueEdit(self)
                c.setFont(self.cue_font)
                c.textEdited.connect(lambda text, c=c: self._on_cue_edited(c, text))
                c.enterPressed.connect(self._focus_block_end)
                self._cue_edits.append(c)
            c = self._cue_edits[i]
            c.block_id = block.userState()
            want = self.cues.get(c.block_id, "")
            if c.text() != want:
                c.setText(want)
            row_top = section_top + round(dl.blockBoundingRect(block).top())
            cfm = QFontMetrics(self.cue_font)
            c.setGeometry(8, row_top + self.baseline - cfm.ascent() - 1, self.lay.cue_width - 14, cfm.height() + 2)
            c.show()
            block, i = block.next(), i + 1
        for c in self._cue_edits[i:]:
            c.hide()
            c.block_id = -1

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()

    # ---------- 그리기 ----------
    def paintEvent(self, _):
        p = QPainter(self)
        lay, lh, w = self.lay, self.lay.line_height, self.width()
        bounds = L.section_bounds(lay, self.used_lines())
        p.fillRect(self.rect(), QColor(COLORS["desk"]))
        p.fillRect(0, 0, w, bounds["todo"][1] + BOTTOM_MARGIN, QColor(COLORS["paper"]))

        head = lay.header_height  # 날짜는 창 위쪽 막대에 있으므로 속지에는 위 여백만
        thin = QPen(QColor(COLORS["rule"]), 1)
        thick = QPen(QColor(COLORS["border"]), 2)
        p.setPen(thick)
        p.drawLine(0, head, w, head)
        for s in L.SECTIONS:
            top, bottom = bounds[s]
            p.setPen(thin)
            y = top + lh
            while y < bottom:
                p.drawLine(0, y, w, y)
                y += lh
            p.setPen(thick)
            p.drawLine(0, bottom, w, bottom)
            if s in SECTION_LABELS:
                p.setFont(self.label_font)
                p.setPen(QColor(COLORS["label"]))
                p.drawText(10, top + self.baseline, SECTION_LABELS[s])
        p.setFont(self.text_font)
        p.setPen(QColor(COLORS["hint"]))
        for s, e in self.edits.items():
            if self.hints[s] and not e.toPlainText():
                p.drawText(e.x(), bounds[s][0] + self.baseline, self.hints[s])
        jt, jb = bounds["journal"]
        p.setPen(QPen(QColor(COLORS["cue_line"]), 1, Qt.DotLine))
        p.drawLine(lay.cue_width, jt + 1, lay.cue_width, jb - 1)

    # ---------- 끌기 / 확대 ----------
    def _on_drag(self, name: str, delta: int) -> None:
        if self._drag_start_layout is None:
            self._drag_start_layout = self.lay
        base = self._drag_start_layout
        new = L.resize_cue(base, delta) if name == "cue" else L.resize_section(base, name, delta)
        if new != self.lay:
            self.set_layout(new)

    def _on_drag_end(self) -> None:
        self._drag_start_layout = None
        self.layoutCommitted.emit(self.lay)

    def zoom_by(self, steps: int) -> None:
        self.set_layout(L.zoom(self.lay, steps))
        self.layoutCommitted.emit(self.lay)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            dy = e.angleDelta().y()
            if dy:
                self.zoom_by(1 if dy > 0 else -1)
            e.accept()
        else:
            e.ignore()

    def _follow_cursor(self) -> None:
        """바깥 스크롤이 커서를 따라가게."""
        edit = self.sender()
        scroll = self._scroll_area()
        if scroll and edit is not None and edit.hasFocus():
            r = edit.cursorRect()
            pt = edit.mapTo(self, r.center())
            scroll.ensureVisible(pt.x(), pt.y(), 0, self.lay.line_height)

    def _scroll_area(self) -> Optional[QScrollArea]:
        w = self.parentWidget()
        while w is not None and not isinstance(w, QScrollArea):
            w = w.parentWidget()
        return w

    # ---------- 일지 문단 ↔ 개요 칸 ----------
    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _on_journal_changed(self) -> None:
        if self._loading:
            return
        doc = self.journal.document()
        old_text = dict(self._prev_text)
        block, seen, prev_block = doc.begin(), set(), None
        while block.isValid():
            bid = block.userState()
            text = block.text()
            if bid < 0 or bid in seen:
                bid = self._new_id()
                block.setUserState(bid)
                self.cues[bid] = ""
                self._prev_text[bid] = text
                # 문단 맨 앞에서 Enter: 위 문단이 비고 내용이 아래로 내려갔으면 타임스탬프도 따라 내려간다
                if prev_block is not None and text.strip():
                    pid = prev_block.userState()
                    if not prev_block.text() and old_text.get(pid) == text:
                        self.cues[bid], self.cues[pid] = self.cues.get(pid, ""), ""
                        self._prev_text[pid] = ""
            seen.add(bid)
            if needs_stamp(self.cues.get(bid, ""), self._prev_text.get(bid, ""), text):
                self.cues[bid] = format_stamp(self.clock())
            self._prev_text[bid] = text
            prev_block, block = block, block.next()
        self.request_relayout()

    def _on_any_changed(self) -> None:
        if not self._loading:
            self.edited.emit()
        self.request_relayout()

    def _on_cue_edited(self, cue: CueEdit, text: str) -> None:
        if cue.block_id >= 0:
            self.cues[cue.block_id] = text
            self.edited.emit()

    def _focus_block_end(self, block_id: int) -> None:
        block = self.journal.document().begin()
        while block.isValid() and block.userState() != block_id:
            block = block.next()
        if block.isValid():
            cur = QTextCursor(block)
            cur.movePosition(QTextCursor.EndOfBlock)
            self.journal.setTextCursor(cur)
            self.journal.setFocus()

    def stamp_current(self) -> None:
        """Ctrl+T: 지금 문단의 개요 칸이 비었으면 현재 시각을 넣고, 무언가 있으면 비운다."""
        focus = QApplication.focusWidget()
        if isinstance(focus, CueEdit):
            bid = focus.block_id
        else:  # 본문 커서가 있는 문단
            bid = self.journal.textCursor().block().userState()
        if bid < 0:
            return
        self.cues[bid] = "" if self.cues.get(bid, "").strip() else format_stamp(self.clock())
        self.edited.emit()
        self.relayout()

    def focused_edit(self) -> Optional[RuledEdit]:
        """굵게/밑줄을 적용할 칸. 타임스탬프 칸에 있을 때는 없음."""
        if isinstance(QApplication.focusWidget(), CueEdit):
            return None
        return self.active_edit

    # ---------- 불러오기 / 모으기 ----------
    def load(self, page: Page, hint_todo: list[str]) -> None:
        self._loading = True
        self.schedule.setPlainText("\n".join(page.schedule))
        self.todo.setPlainText("\n".join(page.todo))
        hint = [t for t in hint_todo if t.strip()]
        self.hints["todo"] = ("지난번 적은 할 일: " + " · ".join(hint)) if hint else ""
        self.journal.setPlainText("\n".join(e.text.replace("\n", " ") for e in page.journal))
        self.cues.clear()
        self._prev_text.clear()
        block, i = self.journal.document().begin(), 0
        while block.isValid():
            bid = self._new_id()
            block.setUserState(bid)
            self.cues[bid] = page.journal[i].cue if i < len(page.journal) else ""
            self._prev_text[bid] = block.text()
            block, i = block.next(), i + 1
        for sec, e in self.edits.items():
            e.apply_marks(page.fmt.get(sec, []))
        self._apply_metrics()
        for e in self.edits.values():
            e.document().clearUndoRedoStacks()
            e.moveCursor(QTextCursor.End)
        self._loading = False
        self.relayout()

    def collect(self, date: dt.date) -> Page:
        entries = []
        block = self.journal.document().begin()
        while block.isValid():
            entries.append(Entry(self.cues.get(block.userState(), ""), block.text().replace("\u2028", " ")))
            block = block.next()
        while entries and entries[-1].is_empty():
            entries.pop()
        fmt = {sec: e.marks() for sec, e in self.edits.items()}
        return Page(date, schedule=self.schedule.lines(), journal=entries, todo=self.todo.lines(),
                    fmt={k: v for k, v in fmt.items() if v})


class MainWindow(QMainWindow):
    saved = Signal()            # 저장 내용이 바뀜(위젯이 다시 읽도록)
    fontChanged = Signal(str)   # 프로그램 글꼴이 바뀜
    quitRequested = Signal()    # 프로그램 종료(창만 닫는 것과 구분)

    def __init__(self, storage: Storage, clock: Callable[[], dt.datetime] = dt.datetime.now,
                 start_date: Optional[dt.date] = None):
        super().__init__()
        self.storage = storage
        self.clock = clock
        self.date: dt.date = start_date or clock().date()
        self.dirty = False
        self.setWindowTitle("메모+일지")
        self.resize(760, 920)

        self.sheet = Sheet(storage.load_layout(), clock)
        self.sheet.set_font_family(storage.get_setting("font_family", DEFAULT_FONT))
        self.sheet.edited.connect(self._mark_dirty)
        self.sheet.stateChanged.connect(self._update_indicators)
        self.sheet.layoutCommitted.connect(storage.save_layout)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(self.sheet)
        self.scroll.setStyleSheet(f"QScrollArea {{ background: {COLORS['desk']}; }}")

        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._build_bar())
        v.addWidget(self.scroll, 1)
        self.setCentralWidget(central)
        self._build_menu()

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(1000)
        self.save_timer.timeout.connect(self.save)

        self._load()

    # ---------- 화면 구성 ----------
    def _build_bar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet("QWidget { background: #2b2d31; color: #f2f2f2; }"
                          "QToolButton, QPushButton { border: none; padding: 6px 12px; font-size: 18px; }"
                          "QPushButton#date { font-size: 21px; font-weight: bold; }"
                          "QToolButton:hover, QPushButton:hover { background: #3a3d43; border-radius: 6px; }"
                          # 굵게/밑줄/삽입·수정 표시: 켜진 것은 눌린 모양(파란 테두리)
                          "QToolButton#ind { font-size: 16px; padding: 3px 9px; border: 1px solid transparent;"
                          " border-radius: 5px; min-width: 20px; }"
                          "QToolButton#ind:checked { background: #3d4f73; border: 1px solid #7fa8ff; }"
                          "QToolButton#mode { font-size: 14px; padding: 4px 10px; border: 1px solid #55585f;"
                          " border-radius: 5px; }"
                          "QToolButton#mode:checked { background: #6b4a2b; border: 1px solid #f0a860; }")
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 6, 10, 6)
        prev_btn = QToolButton(text="◀")
        prev_btn.setToolTip("전날 (Ctrl+PgUp)")
        prev_btn.clicked.connect(self.prev_day)
        self.date_btn = QPushButton(objectName="date")
        self.date_btn.setToolTip("눌러서 달력에서 날짜 고르기")
        self.date_btn.clicked.connect(self._pick_date)
        next_btn = QToolButton(text="▶")
        next_btn.setToolTip("다음날 (Ctrl+PgDown)")
        next_btn.clicked.connect(self.next_day)
        today_btn = QPushButton("오늘")
        today_btn.clicked.connect(self.today)
        self.status = QLabel()
        self.status.setStyleSheet("color: #9a9da3; font-size: 13px;")
        # 상태 표시(눌러서 켜고 끌 수도 있음). 눌러도 글 쓰던 칸의 커서가 그대로 있도록 포커스는 받지 않는다.
        self.bold_btn = QToolButton(text="가", objectName="ind", checkable=True)
        f = self.bold_btn.font(); f.setBold(True); self.bold_btn.setFont(f)
        self.bold_btn.setToolTip("굵게 (Ctrl+B)")
        self.bold_btn.clicked.connect(self._bold)
        self.underline_btn = QToolButton(text="가", objectName="ind", checkable=True)
        f = self.underline_btn.font(); f.setUnderline(True); self.underline_btn.setFont(f)
        self.underline_btn.setToolTip("밑줄 (Ctrl+U)")
        self.underline_btn.clicked.connect(self._underline)
        self.mode_btn = QToolButton(text="삽입", objectName="mode", checkable=True)
        self.mode_btn.setToolTip("삽입 / 수정(겹쳐 쓰기) 전환 (Insert)")
        self.mode_btn.clicked.connect(self.sheet.toggle_overwrite)
        for w in (prev_btn, self.date_btn, next_btn, today_btn):
            h.addWidget(w)
        h.addStretch(1)
        h.addWidget(self.status)
        h.addSpacing(8)
        for w in (self.bold_btn, self.underline_btn, self.mode_btn):
            w.setFocusPolicy(Qt.NoFocus)
            h.addWidget(w)
        return bar

    def _update_indicators(self) -> None:
        e = self.sheet.focused_edit()
        self.bold_btn.setChecked(bool(e and e.is_bold()))
        self.underline_btn.setChecked(bool(e and e.is_underline()))
        self.mode_btn.setChecked(self.sheet.overwrite)
        self.mode_btn.setText("수정" if self.sheet.overwrite else "삽입")

    def _add_actions(self, menu: QMenu, items) -> None:
        """items: (글, 실행할 함수, 단축키 목록) 또는 None(구분선). 단축키는 메뉴 오른쪽에 표시됨."""
        for item in items:
            if item is None:
                menu.addSeparator()
                continue
            text, slot, keys = item
            act = QAction(text, self)
            if keys:
                act.setShortcuts([QKeySequence(k) for k in keys])
            act.triggered.connect(slot)
            menu.addAction(act)
            self.addAction(act)  # 메뉴가 닫혀 있어도 단축키 동작

    def _build_menu(self) -> None:
        mb = self.menuBar()
        self._add_actions(mb.addMenu("파일"), [
            ("JSON으로 백업 내보내기…", self._export_json, []),
            ("JSON 백업 가져오기(합치기)…", self._import_json, []),
            ("TXT로 내보내기…", self._export_text, []),
            None,
            ("창 닫기 (위젯은 계속 떠 있음)", self.close, ["Ctrl+W"]),
            ("프로그램 종료", self.quitRequested.emit, ["Ctrl+Q"]),
        ])
        self._add_actions(mb.addMenu("편집"), [
            ("타임스탬프 넣기/빼기", self.sheet.stamp_current, ["Ctrl+T"]),
            None,
            ("굵게", self._bold, ["Ctrl+B"]),
            ("밑줄", self._underline, ["Ctrl+U"]),
            ("삽입/수정 전환 (Insert)", self.sheet.toggle_overwrite, []),
        ])
        self._add_actions(mb.addMenu("이동"), [
            ("전날", self.prev_day, ["Ctrl+PgUp"]),
            ("다음날", self.next_day, ["Ctrl+PgDown"]),
            ("오늘", self.today, []),
            ("날짜 고르기…", self._pick_date, []),
        ])
        self._add_actions(mb.addMenu("보기"), [
            ("크게", lambda: self.sheet.zoom_by(1), ["Ctrl+=", "Ctrl++"]),
            ("작게", lambda: self.sheet.zoom_by(-1), ["Ctrl+-"]),
            None,
            ("글꼴 바꾸기…", self._choose_font, []),
            ("속지 배치 처음대로", self._reset_layout, []),
        ])
        self._add_actions(mb.addMenu("도움말"), [
            ("단축키 목록", self.show_shortcuts, ["F1"]),
        ])

    def shortcuts_html(self) -> str:
        def rows(title, items):
            head = f"<tr><td colspan=2 style='padding:10px 0 4px 0'><b style='font-size:15px'>{title}</b></td></tr>"
            return head + "".join(
                f"<tr><td style='padding:3px 18px 3px 0'><b>{k}</b></td><td>{v}</td></tr>" for k, v in items)
        return f"<table>{rows('단축키', SHORTCUTS)}{rows('마우스', MOUSE_HELP)}</table>"

    def show_shortcuts(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("도움말")
        box.setTextFormat(Qt.RichText)
        box.setText(self.shortcuts_html())
        box.exec()

    def _bold(self) -> None:
        e = self.sheet.focused_edit()
        if e:
            e.toggle_bold()
        self._update_indicators()

    def _underline(self) -> None:
        e = self.sheet.focused_edit()
        if e:
            e.toggle_underline()
        self._update_indicators()

    def prev_day(self) -> None:
        self.go_to(self.date - dt.timedelta(days=1))

    def next_day(self) -> None:
        self.go_to(self.date + dt.timedelta(days=1))

    def today(self) -> None:
        self.go_to(self.clock().date())

    def _choose_font(self) -> None:
        """설치된 글꼴 중 하나를 프로그램 전체 글꼴로(한글 되는 글꼴만 보여줌). 고르는 즉시 미리보기."""
        before = self.sheet.font_family
        dlg = QDialog(self)
        dlg.setWindowTitle("글꼴 바꾸기")
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel("속지에 쓸 글꼴 (고르면 바로 미리 보입니다)"))
        combo = QFontComboBox()
        combo.setWritingSystem(QFontDatabase.Korean)
        combo.setCurrentFont(QFont(before))
        combo.currentFontChanged.connect(lambda f: self.sheet.set_font_family(f.family()))
        v.addWidget(combo)
        reset = QPushButton(f"기본 글꼴({DEFAULT_FONT})로")
        reset.clicked.connect(lambda: combo.setCurrentFont(QFont(DEFAULT_FONT)))
        v.addWidget(reset)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        v.addWidget(buttons)
        if dlg.exec() == QDialog.Accepted:
            self.storage.set_setting("font_family", self.sheet.font_family)
            self.fontChanged.emit(self.sheet.font_family)
        else:
            self.sheet.set_font_family(before)

    def _pick_date(self) -> None:
        menu = QMenu(self)
        cal = QCalendarWidget()
        cal.setStyleSheet("QCalendarWidget { font-size: 16px; }")
        cal.setMinimumSize(360, 300)
        cal.setFirstDayOfWeek(Qt.Sunday)
        cal.setGridVisible(False)
        cal.setSelectedDate(QDate(self.date.year, self.date.month, self.date.day))

        def chosen(qd: QDate):
            menu.close()
            self.go_to(dt.date(qd.year(), qd.month(), qd.day()))

        cal.clicked.connect(chosen)
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(cal)
        menu.addAction(wa)
        menu.exec(self.date_btn.mapToGlobal(self.date_btn.rect().bottomLeft()))

    def _reset_layout(self) -> None:
        self.sheet.set_layout(L.PageLayout())
        self.storage.save_layout(self.sheet.lay)

    # ---------- 저장 / 이동 ----------
    def _load(self) -> None:
        page = self.storage.get_page(self.date)
        hint = [] if any(t.strip() for t in page.todo) else self.storage.previous_todo(self.date)
        self.sheet.load(page, hint)
        self.date_btn.setText(date_label(self.date))
        self.dirty = False
        self.status.setText("")
        self.scroll.verticalScrollBar().setValue(0)

    def _mark_dirty(self) -> None:
        self.dirty = True
        self.status.setText("입력 중…")
        self.save_timer.start()

    def save(self) -> None:
        self.save_timer.stop()
        if not self.dirty:
            return
        self.storage.save_page(self.sheet.collect(self.date))
        self.dirty = False
        self.status.setText(f"저장됨 {self.clock():%H:%M:%S}")
        self.saved.emit()

    def go_to(self, date: dt.date) -> None:
        if date == self.date:
            return
        self.save()
        self.date = date
        self._load()

    def open_date(self, date: dt.date) -> None:
        """위젯/트레이에서 부를 때: 그 날짜 속지를 열고 창을 앞으로."""
        self.go_to(date)
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        self.sheet.journal.setFocus()

    def closeEvent(self, e):
        self.save()
        self.storage.save_layout(self.sheet.lay)
        super().closeEvent(e)

    # ---------- 내보내기 ----------
    def _export_json(self) -> None:
        self.save()
        path, _ = QFileDialog.getSaveFileName(self, "JSON 백업", f"메모일지_{self.clock():%Y%m%d}.json", "JSON (*.json)")
        if path:
            n = self.storage.export_json(path)
            QMessageBox.information(self, "내보내기", f"{n}일치를 저장했습니다.\n{path}")

    def _import_json(self) -> None:
        self.save()
        path, _ = QFileDialog.getOpenFileName(self, "JSON 백업 가져오기", "", "JSON (*.json)")
        if not path:
            return
        try:
            r = self.storage.import_json(path)
        except (ValueError, OSError) as ex:
            QMessageBox.warning(self, "가져오기 실패", str(ex))
            return
        self._load()
        self.saved.emit()
        QMessageBox.information(self, "가져오기",
                                f"새로 추가 {r.added}일, 더 최신이라 바꿈 {r.updated}일, 이쪽이 최신이라 둠 {r.skipped}일")

    def _export_text(self) -> None:
        self.save()
        path, _ = QFileDialog.getSaveFileName(self, "TXT 내보내기", f"메모일지_{self.clock():%Y%m%d}.txt", "텍스트 (*.txt)")
        if path:
            n = self.storage.export_text(path)
            QMessageBox.information(self, "내보내기", f"{n}일치를 저장했습니다.\n{path}")
