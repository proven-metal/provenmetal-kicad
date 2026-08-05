import unittest

from _bootstrap import *  # noqa: F401,F403 (sys.path bootstrap)

from provenmetal_kicad.verdict import verdict_for, summarize, SOURCEABLE_WITHIN_DAYS


class TestVerdict(unittest.TestCase):
    def test_in_stock_for_full_build_passes(self):
        self.assertEqual(verdict_for("matched", 100, 60, 100), "pass")

    def test_stock_below_required_is_not_in_stock(self):
        self.assertEqual(verdict_for("matched", 99, 60, 100), "fail")

    def test_sourceable_within_a_week_passes(self):
        self.assertEqual(verdict_for("matched", 0, SOURCEABLE_WITHIN_DAYS, 10), "pass")
        self.assertEqual(verdict_for("matched", 0, SOURCEABLE_WITHIN_DAYS + 1, 10), "fail")

    def test_unmatched_fails(self):
        self.assertEqual(verdict_for("unmatched", None, None, 1), "fail")

    def test_manual_or_unknown_is_review(self):
        self.assertEqual(verdict_for("manual", None, None, 1), "review")
        self.assertEqual(verdict_for("matched", None, None, 1), "review")
        self.assertEqual(verdict_for(None, None, None, 1), "review")

    def test_partial_stock_unknown_lead_fails(self):
        self.assertEqual(verdict_for("matched", 3, None, 10), "fail")

    def test_summarize(self):
        self.assertEqual(
            summarize(["pass", "pass", "review", "fail"]),
            {"total": 4, "pass": 2, "review": 1, "fail": 1},
        )


if __name__ == "__main__":
    unittest.main()
