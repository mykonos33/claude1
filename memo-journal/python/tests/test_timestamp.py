import datetime as dt
import unittest

from timestamp import (
    ScheduleItem as S, format_ampm, format_item_time, format_stamp, needs_stamp,
    parse_schedule, parse_schedule_line, parse_stamp,
)


class StampTest(unittest.TestCase):
    def test_format(self):
        self.assertEqual(format_stamp(dt.datetime(2026, 11, 10, 9, 5)), "[09:05]")
        self.assertEqual(format_stamp(dt.time(21, 30)), "[21:30]")

    def test_parse_is_tolerant(self):
        self.assertEqual(parse_stamp("[09:05]"), "09:05")
        self.assertEqual(parse_stamp(" 9:05 "), "09:05")
        self.assertEqual(parse_stamp("[21 : 30]"), "21:30")
        self.assertIsNone(parse_stamp("업무 후"))
        self.assertIsNone(parse_stamp("[25:00]"))
        self.assertIsNone(parse_stamp(""))

    def test_needs_stamp(self):
        self.assertTrue(needs_stamp("", "", "a"))
        self.assertFalse(needs_stamp("[09:00]", "", "a"))   # 이미 있음
        self.assertFalse(needs_stamp("", "abc", "abcd"))     # 사용자가 지운 칸은 다시 안 채움
        self.assertFalse(needs_stamp("", "", "   "))
        self.assertFalse(needs_stamp("업무 후", "", "a"))     # 개요 칸 자유 텍스트 존중


class ScheduleTest(unittest.TestCase):
    def test_lines(self):
        self.assertEqual(parse_schedule_line("21:00~22:00 새 일정"), S("21:00", "22:00", "새 일정"))
        self.assertEqual(parse_schedule_line("[9:30] 회의"), S("09:30", None, "회의"))
        self.assertEqual(parse_schedule_line("14:00-15:30 면담"), S("14:00", "15:30", "면담"))
        self.assertEqual(parse_schedule_line("서류 제출"), S(None, None, "서류 제출"))
        self.assertEqual(parse_schedule_line("10:00"), S("10:00", None, "새 일정"))
        self.assertEqual(parse_schedule_line("99:00 이상한 시각"), S(None, None, "99:00 이상한 시각"))
        self.assertIsNone(parse_schedule_line("   "))

    def test_sorted(self):
        items = parse_schedule(["15:00 B", "", "종일 일", "09:00 A"])
        self.assertEqual([i.title for i in items], ["종일 일", "A", "B"])

    def test_widget_text(self):
        self.assertEqual(format_ampm("21:00"), "오후 9:00")
        self.assertEqual(format_ampm("00:30"), "오전 12:30")
        self.assertEqual(format_ampm("12:00"), "오후 12:00")
        self.assertEqual(format_item_time(parse_schedule_line("21:00~22:00 새 일정")), "오후 9:00 ~ 오후 10:00")
        self.assertEqual(format_item_time(parse_schedule_line("메모")), "종일")


if __name__ == "__main__":
    unittest.main()
