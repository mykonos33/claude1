import datetime as dt
import unittest

from calendar_core import date_label, day_kind, month_grid, shift_month


class CalendarTest(unittest.TestCase):
    def test_november_2026_matches_widget_photo(self):
        weeks = month_grid(2026, 11)
        self.assertEqual(len(weeks), 5)
        self.assertEqual(weeks[0][0].date, dt.date(2026, 11, 1))  # 1일이 일요일
        last = weeks[-1]
        self.assertEqual([d.date.day for d in last], [29, 30, 1, 2, 3, 4, 5])
        self.assertEqual([d.in_month for d in last], [True, True] + [False] * 5)

    def test_grid_sizes(self):
        self.assertEqual(len(month_grid(2026, 2)), 4)  # 2026-02-01 일요일, 28일
        self.assertEqual(len(month_grid(2026, 8)), 6)  # 8/1 토요일, 31일
        for y in (1999, 2024, 2100):
            for m in range(1, 13):
                for week in month_grid(y, m):
                    self.assertEqual(len(week), 7)
                    self.assertEqual(week[0].kind, "sun")
                    self.assertEqual(week[6].kind, "sat")

    def test_shift_month(self):
        self.assertEqual(shift_month(2026, 11, 2), (2027, 1))
        self.assertEqual(shift_month(2026, 1, -1), (2025, 12))
        self.assertEqual(shift_month(2026, 11, -24), (2024, 11))
        with self.assertRaises(ValueError):
            shift_month(9999, 12, 1)

    def test_labels(self):
        self.assertEqual(date_label(dt.date(2026, 11, 10)), "2026-11-10 (화)")
        self.assertEqual(day_kind(dt.date(2026, 11, 14)), "sat")


if __name__ == "__main__":
    unittest.main()
