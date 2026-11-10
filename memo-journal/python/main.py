"""메모+일지 실행 진입점.

    python main.py               # 캘린더 위젯 + 트레이 아이콘 + 오늘 속지 창
    python main.py --widget-only # 위젯과 트레이만(윈도우 시작 프로그램용)
    python main.py --db 경로.db   # 다른 저장 파일 사용(시험용 등)

창을 닫아도 프로그램은 트레이에 남는다. 끝내려면 트레이/위젯 오른쪽 클릭 → 프로그램 종료.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sys
from typing import Callable, Optional

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from main_window import MainWindow
from storage import Storage, default_db_path
from widget import CalendarWidget, make_app_icon


class Controller(QObject):
    """메인 창, 위젯, 트레이 아이콘을 잇는다."""

    def __init__(self, app: QApplication, storage: Storage,
                 clock: Callable[[], dt.datetime] = dt.datetime.now, use_tray: bool = True):
        super().__init__()
        self.app = app
        self.storage = storage
        self.clock = clock
        icon = make_app_icon()
        app.setWindowIcon(icon)

        self.win = MainWindow(storage, clock)
        self.widget = CalendarWidget(storage, clock, font_family=self.win.sheet.font_family)
        self.win.saved.connect(self.widget.refresh)
        self.win.fontChanged.connect(self.widget.set_font_family)
        self.win.quitRequested.connect(self.quit)
        self.widget.openRequested.connect(self.win.open_date)
        self.widget.hideRequested.connect(lambda: self.set_widget_visible(False))
        self.widget.quitRequested.connect(self.quit)

        self.tray: Optional[QSystemTrayIcon] = None
        self.widget_action: Optional[QAction] = None
        if use_tray and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(icon, self)
            self.tray.setToolTip("메모+일지")
            menu = QMenu()
            menu.addAction("오늘 속지 열기", self.open_today)
            self.widget_action = menu.addAction("캘린더 위젯 보이기")
            self.widget_action.setCheckable(True)
            self.widget_action.toggled.connect(self.set_widget_visible)
            menu.addSeparator()
            menu.addAction("프로그램 종료", self.quit)
            self._tray_menu = menu  # 메뉴가 사라지지 않게 잡아 둠
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self._tray_clicked)
            self.tray.show()
        # 트레이가 없으면 위젯을 숨겼을 때 다시 꺼낼 방법이 없으므로 숨기기를 막고, 창을 닫으면 끝낸다
        self.widget.can_hide = self.tray is not None
        app.setQuitOnLastWindowClosed(self.tray is None)

        visible = storage.get_setting("widget_visible", "1") != "0" or self.tray is None
        self.set_widget_visible(visible)

    def set_widget_visible(self, on: bool) -> None:
        on = bool(on) or not self.widget.can_hide
        self.widget.setVisible(on)
        self.storage.set_setting("widget_visible", "1" if on else "0")
        if self.widget_action is not None and self.widget_action.isChecked() != on:
            self.widget_action.setChecked(on)

    def open_today(self) -> None:
        self.win.open_date(self.clock().date())

    def _tray_clicked(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.open_today()

    def quit(self) -> None:
        self.win.save()
        self.storage.save_layout(self.win.sheet.lay)
        if self.tray is not None:
            self.tray.hide()
        self.widget.close()
        self.win.close()
        self.app.quit()


def _instance_name(db_path: str) -> str:
    return "memo-journal-" + hashlib.sha1(db_path.encode("utf-8")).hexdigest()[:12]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="메모+일지")
    parser.add_argument("--db", default=str(default_db_path()), help="저장 파일 경로")
    parser.add_argument("--widget-only", action="store_true", help="시작할 때 속지 창을 열지 않음")
    args = parser.parse_args(argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("메모+일지")

    # 이미 실행 중이면 새로 띄우지 않고, 떠 있는 쪽의 속지 창만 앞으로 부른다
    name = _instance_name(args.db)
    probe = QLocalSocket()
    probe.connectToServer(name)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(name)  # 비정상 종료로 남은 흔적 정리
    server = QLocalServer()
    server.listen(name)

    storage = Storage(args.db)
    ctl = Controller(app, storage)

    def on_other_instance():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.close()
        ctl.open_today()

    server.newConnection.connect(on_other_instance)
    if not args.widget_only:
        ctl.open_today()
    code = app.exec()
    server.close()
    storage.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
