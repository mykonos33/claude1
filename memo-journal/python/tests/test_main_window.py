"""메인 창 동작 테스트(화면 없이 실행). PySide6가 없으면 건너뜀."""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent, QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None

D = dt.date(2026, 11, 10)


def type_text(widget, text):
    """한글도 보낼 수 있는 키 입력(QTest.keyClicks는 ASCII만 됨)."""
    for ch in text:
        for kind in (QEvent.KeyPress, QEvent.KeyRelease):
            QApplication.sendEvent(widget, QKeyEvent(kind, 0, Qt.NoModifier, ch))


class Clock:
    def __init__(self):
        self.now = dt.datetime(2026, 11, 10, 9, 12)

    def __call__(self):
        return self.now


@unittest.skipIf(QApplication is None, "PySide6 없음")
class MainWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from main_window import MainWindow
        from storage import Storage

        self.tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.tmp.name) / "j.db")
        self.clock = Clock()
        self.win = MainWindow(self.storage, clock=self.clock, start_date=D)
        self.win.resize(700, 900)
        self.win.show()
        self.app.processEvents()

    def tearDown(self):
        self.win.close()
        self.storage.close()
        self.tmp.cleanup()

    def type_journal(self, text):
        type_text(self.win.sheet.journal, text)
        self.app.processEvents()

    def enter(self, w=None):
        QTest.keyClick(w or self.win.sheet.journal, Qt.Key_Return)
        self.app.processEvents()

    def entries(self):
        return [(e.cue, e.text) for e in self.win.sheet.collect(D).journal]

    def test_auto_stamp_on_first_char(self):
        self.type_journal("아침 회의")
        self.enter()
        self.clock.now = dt.datetime(2026, 11, 10, 10, 40)
        self.type_journal("서류 검토")
        self.assertEqual(self.entries(), [("[09:12]", "아침 회의"), ("[10:40]", "서류 검토")])

    def test_cue_is_editable_and_kept(self):
        self.type_journal("회의")
        sheet = self.win.sheet
        cue = next(c for c in sheet._cue_edits if c.isVisible())
        cue.selectAll()
        type_text(cue, "[08:55]")
        self.app.processEvents()
        self.type_journal(" 계속")
        self.assertEqual(self.entries(), [("[08:55]", "회의 계속")])
        cue.clear()
        type_text(cue, "x")
        cue.clear()  # 비워도 본문이 있으면 다시 채우지 않음
        cue.textEdited.emit("")
        self.type_journal("!")
        self.assertEqual(self.entries(), [("", "회의 계속!")])

    def test_enter_at_line_start_moves_stamp_down(self):
        self.type_journal("첫 줄")
        cur = self.win.sheet.journal.textCursor()
        cur.movePosition(QTextCursor.StartOfBlock)
        self.win.sheet.journal.setTextCursor(cur)
        self.enter()
        self.assertEqual(self.entries(), [("", ""), ("[09:12]", "첫 줄")])

    def test_ctrl_t_restamps(self):
        self.type_journal("메모")
        self.clock.now = dt.datetime(2026, 11, 10, 11, 5)
        self.win.sheet.stamp_current()
        self.assertEqual(self.entries(), [("[11:05]", "메모")])

    def test_save_and_reload_other_day(self):
        sheet = self.win.sheet
        type_text(sheet.schedule, "21:00~22:00 새 일정")
        type_text(sheet.todo, "서류 제출")
        self.type_journal("오늘 일")
        self.win.go_to(D + dt.timedelta(days=1))  # 이동하면 저장
        self.assertIn("서류 제출", sheet.hints["todo"])  # 어제 할 일 힌트
        self.assertEqual(sheet.collect(D).journal, [])
        self.win.go_to(D)
        page = self.storage.get_page(D)
        self.assertEqual(page.schedule, ["21:00~22:00 새 일정"])
        self.assertEqual([(e.cue, e.text) for e in page.journal], [("[09:12]", "오늘 일")])
        self.assertEqual(self.entries(), [("[09:12]", "오늘 일")])

    def test_viewing_does_not_touch_storage(self):
        self.win.go_to(D + dt.timedelta(days=3))
        self.win.go_to(D)
        self.assertEqual(self.storage.dates_with_content(2026, 11), set())

    def test_layout_drag_and_rows_align(self):
        import layout as L

        sheet = self.win.sheet
        sheet._on_drag("schedule", sheet.lay.line_height)  # 한 줄 아래로 끌기
        sheet._on_drag_end()
        self.assertEqual(sheet.lay.schedule_lines, 7)
        self.assertEqual(self.storage.load_layout().schedule_lines, 7)
        b = L.section_bounds(sheet.lay, sheet.used_lines())
        self.assertEqual(sheet.journal.y(), b["journal"][0] + sheet.edit_offset)
        # 긴 일지는 구역이 늘어나도 잘리지 않음
        for i in range(20):
            self.type_journal(f"줄 {i}")
            self.enter()
        self.app.processEvents()
        sheet.relayout()
        b = L.section_bounds(sheet.lay, sheet.used_lines())
        self.assertGreaterEqual(b["journal"][1] - b["journal"][0], 21 * sheet.lay.line_height)
        self.assertGreaterEqual(sheet.journal.height(), sheet.journal.document().size().height())

    def test_paste_and_enter_keep_fixed_line_height(self):
        from PySide6.QtCore import QMimeData

        sheet = self.win.sheet
        self.type_journal("가")
        self.enter()
        m = QMimeData()
        m.setText("첫째\r\n둘째")
        sheet.journal.insertFromMimeData(m)
        h = QMimeData()
        h.setHtml("<h1>제목</h1>")
        sheet.journal.insertFromMimeData(h)
        self.app.processEvents()
        block, heights = sheet.journal.document().begin(), []
        while block.isValid():
            heights.append(block.blockFormat().lineHeight())
            block = block.next()
        self.assertEqual(heights, [sheet.lay.line_height] * 3)
        self.assertEqual([t for _, t in self.entries()], ["가", "첫째", "둘째제목"])
        self.assertEqual(sheet.journal.visual_lines(), 3)

    def test_zoom_changes_line_height(self):
        sheet = self.win.sheet
        lh = sheet.lay.line_height
        sheet.zoom_by(2)
        self.assertEqual(sheet.lay.line_height, lh + 4)
        self.type_journal("확대 후")
        self.assertEqual(sheet.journal.visual_lines(), 1)


if __name__ == "__main__":
    unittest.main()
