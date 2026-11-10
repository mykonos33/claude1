import unittest

from layout import PageLayout, hit_divider, page_height, resize_cue, resize_section, section_bounds, zoom


class LayoutTest(unittest.TestCase):
    def test_defaults_match_sketch(self):
        l = PageLayout()
        self.assertEqual((l.schedule_lines, l.journal_lines, l.todo_lines), (4, 12, 3))
        b = section_bounds(l)
        self.assertEqual(b["schedule"], (10, 10 + 4 * 28))
        self.assertEqual(b["journal"][0], b["schedule"][1])
        self.assertEqual(page_height(l), 10 + 19 * 28)

    def test_drag_snaps_to_lines(self):
        l = PageLayout()
        self.assertEqual(resize_section(l, "schedule", 30).schedule_lines, 5)
        self.assertEqual(resize_section(l, "schedule", 10).schedule_lines, 4)   # 반 줄 미만은 그대로
        self.assertEqual(resize_section(l, "journal", -28 * 3).journal_lines, 9)
        self.assertEqual(resize_section(l, "todo", -1000).todo_lines, 1)        # 최소 1줄
        with self.assertRaises(ValueError):
            resize_section(l, "nope", 10)

    def test_content_grows_section(self):
        l = PageLayout()
        b = section_bounds(l, {"journal": 20})
        self.assertEqual(b["journal"][1] - b["journal"][0], 21 * 28)

    def test_hit_divider(self):
        l = PageLayout()
        y = section_bounds(l)["journal"][1]
        self.assertEqual(hit_divider(l, y + 2), "journal")
        self.assertIsNone(hit_divider(l, y + 14))

    def test_cue_and_zoom(self):
        l = PageLayout()
        self.assertEqual(resize_cue(l, 40).cue_width, 130)
        self.assertEqual(resize_cue(l, -500).cue_width, 48)
        z = zoom(l, 2)
        self.assertEqual(z.line_height, 32)
        self.assertGreater(z.cue_width, l.cue_width)
        self.assertEqual(zoom(l, -100).line_height, 18)

    def test_dict_roundtrip_and_bad_values(self):
        l = resize_section(PageLayout(), "schedule", 28)
        self.assertEqual(PageLayout.from_dict(l.to_dict()), l)
        self.assertNotIn("header_height", l.to_dict())
        self.assertEqual(PageLayout.from_dict({"header_height": 36}).header_height, 10)  # 옛 설정 무시
        bad = PageLayout.from_dict({"journal_lines": "abc", "todo_lines": 999, "unknown": 1})
        self.assertEqual(bad.journal_lines, 12)
        self.assertEqual(bad.todo_lines, 30)


if __name__ == "__main__":
    unittest.main()
