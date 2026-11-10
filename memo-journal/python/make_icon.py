"""exe에 넣을 아이콘 파일(.ico)을 만든다. 빌드할 때 한 번 실행.

    python make_icon.py build/app.ico
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from widget import make_app_icon


def main(out: str) -> int:
    app = QApplication.instance() or QApplication([])
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = make_app_icon(256).pixmap(256, 256).save(str(path), "ICO")
    print(("만듦: " if ok else "실패: ") + str(path))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "build/app.ico"))
