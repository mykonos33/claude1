"""윈도우 시작 시 자동 실행(5단계).

현재 사용자의 시작 프로그램 레지스트리(HKCU\\...\\Run)에 한 줄을 넣고 뺀다.
관리자 권한이 필요 없고, 다른 사용자에게는 영향이 없다. 윈도우가 아니면 지원하지 않는다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "MemoJournal"


def is_supported() -> bool:
    return sys.platform == "win32"


def launch_command(db_path: Optional[str] = None, *, frozen: Optional[bool] = None,
                   executable: Optional[str] = None, script: Optional[str] = None) -> str:
    """시작 프로그램에 등록할 명령. 속지 창 없이 위젯과 트레이만 띄운다(--widget-only).

    exe로 묶은 경우: "MemoJournal.exe" --widget-only
    파이썬으로 실행한 경우: "pythonw.exe" "main.py" --widget-only  (pythonw = 검은 창 없이 실행)
    """
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    executable = executable or sys.executable
    if frozen:
        parts = [executable]
    else:
        exe = Path(executable)
        pythonw = exe.with_name("pythonw.exe")
        if exe.name.lower() == "python.exe" and pythonw.exists():
            exe = pythonw
        parts = [str(exe), script or str(Path(__file__).with_name("main.py"))]
    parts.append("--widget-only")
    if db_path:
        parts += ["--db", str(db_path)]
    return subprocess.list2cmdline(parts)


def _winreg():
    import winreg  # 윈도우에만 있음
    return winreg


def is_enabled(reg=None) -> bool:
    reg = reg or _winreg()
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY) as key:
            reg.QueryValueEx(key, VALUE_NAME)
            return True
    except OSError:
        return False


def registered_command(reg=None) -> Optional[str]:
    reg = reg or _winreg()
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return reg.QueryValueEx(key, VALUE_NAME)[0]
    except OSError:
        return None


def set_enabled(on: bool, command: Optional[str] = None, reg=None) -> None:
    reg = reg or _winreg()
    with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
        if on:
            reg.SetValueEx(key, VALUE_NAME, 0, reg.REG_SZ, command or launch_command())
        else:
            try:
                reg.DeleteValue(key, VALUE_NAME)
            except OSError:
                pass  # 이미 없음
