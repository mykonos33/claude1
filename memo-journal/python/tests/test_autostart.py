import unittest
from contextlib import contextmanager

import autostart


class FakeReg:
    """winreg 흉내(윈도우가 아닌 곳에서도 테스트하려고)."""
    HKEY_CURRENT_USER, KEY_SET_VALUE, REG_SZ = "HKCU", 2, 1

    def __init__(self):
        self.values = {}

    @contextmanager
    def OpenKey(self, root, path, reserved=0, access=0):
        assert (root, path) == ("HKCU", autostart.RUN_KEY)
        yield "key"

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


class AutostartTest(unittest.TestCase):
    def test_command_for_exe(self):
        cmd = autostart.launch_command(frozen=True, executable=r"C:\Program Files\메모\MemoJournal.exe")
        self.assertEqual(cmd, r'"C:\Program Files\메모\MemoJournal.exe" --widget-only')

    def test_command_for_python(self):
        cmd = autostart.launch_command(frozen=False, executable=r"C:\Py\python.exe", script=r"C:\my app\main.py")
        self.assertEqual(cmd, r'C:\Py\python.exe "C:\my app\main.py" --widget-only')
        cmd = autostart.launch_command(r"D:\data\j.db", frozen=True, executable=r"C:\M.exe")
        self.assertEqual(cmd, r"C:\M.exe --widget-only --db D:\data\j.db")

    def test_enable_disable(self):
        reg = FakeReg()
        self.assertFalse(autostart.is_enabled(reg))
        self.assertIsNone(autostart.registered_command(reg))
        autostart.set_enabled(True, "cmd --widget-only", reg)
        self.assertTrue(autostart.is_enabled(reg))
        self.assertEqual(autostart.registered_command(reg), "cmd --widget-only")
        autostart.set_enabled(False, reg=reg)
        autostart.set_enabled(False, reg=reg)  # 두 번 꺼도 오류 없음
        self.assertFalse(autostart.is_enabled(reg))


if __name__ == "__main__":
    unittest.main()
