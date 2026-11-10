"""메모+일지 실행 진입점.

    python main.py              # 기본 저장 위치 사용
    python main.py --db 경로.db  # 다른 저장 파일 사용(시험용 등)
"""
from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication

from main_window import MainWindow
from storage import Storage, default_db_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="메모+일지")
    parser.add_argument("--db", default=str(default_db_path()), help="저장 파일 경로")
    args = parser.parse_args(argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("메모+일지")
    storage = Storage(args.db)
    win = MainWindow(storage)
    win.show()
    code = app.exec()
    storage.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
