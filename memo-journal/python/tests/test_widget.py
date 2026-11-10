"""캘린더 위젯과 창 연결 테스트(화면 없이 실행). PySide6가 없으면 건너뜀."""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None

D = dt.date(2026, 11, 10)


class Clock:
    def __init__(self):
        self.now = dt.datetime(2026, 11, 10, 9, 12)

    def __call__(self):
        return self.now


@unittest.skipIf(QApplication is None, "PySide6 없음")
class WidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from storage import Entry, Page, Storage
        from widget import CalendarWidget

        self.tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.tmp.name) / "j.db")
        self.storage.save_page(Page(D, schedule=["21:00~22:00 새 일정", "09:30 회의"]))
        self.storage.save_page(Page(dt.date(2026, 11, 12), journal=[Entry("[10:00]", "일지만")]))
        self.storage.save_page(Page(dt.date(2026, 11, 20), schedule=["14:00 면담"]))
        self.storage.save_page(Page(dt.date(2026, 12, 3), schedule=["다음 달 일정"]))
        self.clock = Clock()
        self.w = CalendarWidget(self.storage, self.clock)
        self.w.show()
        self.app.processEvents()

    def tearDown(self):
        self.w.close()
        self.storage.close()
        self.tmp.cleanup()

    def click_date(self, date, double=False):
        pos = self.w.date_rect(date).center()
        (QTest.mouseDClick if double else QTest.mouseClick)(self.w, Qt.LeftButton, Qt.NoModifier, pos)
        self.app.processEvents()

    def test_today_overview_like_photo(self):
        w = self.w
        self.assertEqual((w.year, w.month, w.selected), (2026, 11, D))
        self.assertEqual(w.header, "오늘 · 11월 10일 (화)")
        self.assertEqual(w.rows, [("회의", "오전 9:30", True), ("새 일정", "오후 9:00 ~ 오후 10:00", True)])
        self.assertTrue(w.dots[D])                          # 일정 있는 날
        self.assertFalse(w.dots[dt.date(2026, 11, 12)])     # 일지만 있는 날
        self.assertTrue(w.dots[dt.date(2026, 12, 3)])       # 흐리게 보이는 다음 달 날짜

    def test_window_flags(self):
        flags = self.w.windowFlags()
        self.assertTrue(flags & Qt.FramelessWindowHint)
        self.assertTrue(flags & Qt.WindowStaysOnBottomHint)
        self.assertEqual(flags & Qt.WindowType_Mask, Qt.Tool)  # 작업표시줄에 안 뜸

    def test_click_selects_day_and_shows_upcoming(self):
        self.click_date(dt.date(2026, 11, 12))
        w = self.w
        self.assertEqual(w.selected, dt.date(2026, 11, 12))
        self.assertEqual(w.header, "11월 12일 (목)")
        self.assertTrue(w.no_items)
        self.assertEqual(w.rows[0], ("면담", "11/20 (금) 오후 2:00", False))
        self.assertEqual(w.rows[1], ("다음 달 일정", "12/3 (목) 종일", False))

    def test_month_navigation(self):
        w = self.w
        QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, w.arrow_rects()[1].center())
        self.assertEqual((w.year, w.month), (2026, 12))
        QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, w.arrow_rects()[-1].center())
        QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, w.arrow_rects()[-1].center())
        self.assertEqual((w.year, w.month), (2026, 10))
        w.go_month(-12 * 30)                                # 영구 캘린더: 30년 전
        self.assertEqual((w.year, w.month), (1996, 10))
        QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, w.title_rect().center())
        self.assertEqual((w.year, w.month, w.selected), (2026, 11, D))
        self.click_date(dt.date(2026, 12, 3))               # 흐린 다음 달 날짜 → 그 달로
        self.assertEqual((w.year, w.month), (2026, 12))

    def test_double_click_opens_date(self):
        got = []
        self.w.openRequested.connect(got.append)
        self.click_date(dt.date(2026, 11, 20), double=True)
        self.assertEqual(got, [dt.date(2026, 11, 20)])

    def test_drag_moves_and_remembers(self):
        from widget import CalendarWidget

        w = self.w
        w.move(100, 100)
        start = QPoint(w.width() - 30, w.height() - 20)
        QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(w, start + QPoint(60, 40))
        QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, start + QPoint(60, 40))
        self.assertEqual(self.storage.get_setting("widget_pos"), f"{w.x()},{w.y()}")
        self.assertNotEqual((w.x(), w.y()), (100, 100))
        w2 = CalendarWidget(self.storage, self.clock)
        self.assertEqual(w2.pos(), w.pos())
        w2.close()

    def test_scale_saved(self):
        from widget import CalendarWidget, W

        self.w.set_scale(1.3)
        self.assertEqual(self.w.width(), round(W * 1.3))
        self.w.set_scale(9)
        self.assertEqual(self.w.scale, 1.8)
        w2 = CalendarWidget(self.storage, self.clock)
        self.assertEqual(w2.scale, 1.8)
        w2.close()

    def test_midnight_rollover(self):
        w = self.w
        self.clock.now = dt.datetime(2026, 12, 1, 0, 0, 5)
        w.today = dt.date(2026, 11, 30)
        w.selected = w.today
        w.check_day_change()
        self.assertEqual((w.today, w.selected, w.month), (dt.date(2026, 12, 1), dt.date(2026, 12, 1), 12))

    def test_many_items_overflow_and_paint(self):
        from storage import Page

        self.storage.save_page(Page(D, schedule=[f"{h:02d}:00 일정 {h}" for h in range(8, 18)]))
        self.w.refresh()
        self.assertEqual(len(self.w.rows), 10)
        img = self.w.grab().toImage()                        # 그리다 죽지 않는지
        self.assertEqual(img.width(), self.w.width())


@unittest.skipIf(QApplication is None, "PySide6 없음")
class ControllerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from main import Controller
        from storage import Storage

        self.tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.tmp.name) / "j.db")
        self.clock = Clock()
        self.ctl = Controller(self.app, self.storage, clock=self.clock, use_tray=False)

    def tearDown(self):
        self.ctl.win.close()
        self.ctl.widget.close()
        self.app.setQuitOnLastWindowClosed(True)
        self.storage.close()
        self.tmp.cleanup()

    def test_widget_opens_sheet_and_sees_saved_schedule(self):
        ctl = self.ctl
        target = dt.date(2026, 11, 20)
        ctl.widget.openRequested.emit(target)
        self.assertTrue(ctl.win.isVisible())
        self.assertEqual(ctl.win.date, target)
        for ch in "15:00 보고":
            from PySide6.QtCore import QEvent
            from PySide6.QtGui import QKeyEvent
            QApplication.sendEvent(ctl.win.sheet.schedule, QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, ch))
        ctl.win.save()                                       # 저장되면 위젯이 바로 다시 읽음
        self.assertTrue(ctl.widget.dots[target])
        ctl.widget.select(target)
        self.assertEqual(ctl.widget.rows, [("보고", "오후 3:00", True)])

    def test_without_tray_widget_cannot_be_hidden(self):
        ctl = self.ctl
        self.assertFalse(ctl.widget.can_hide)
        ctl.set_widget_visible(False)
        self.assertTrue(ctl.widget.isVisible())


if __name__ == "__main__":
    unittest.main()
