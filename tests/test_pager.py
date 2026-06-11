import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
PYTHON_DIR = os.path.join(ROOT, "python")
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

from cinbase import pager


class PaginateTests(unittest.TestCase):
    def test_empty_list_has_no_pages(self):
        self.assertEqual(pager.paginate([], 6), [])

    def test_single_partial_page(self):
        self.assertEqual(pager.paginate(["a", "b"], 6), [["a", "b"]])

    def test_exact_multiple_pages(self):
        self.assertEqual(
            pager.paginate(list("abcdef"), 3),
            [["a", "b", "c"], ["d", "e", "f"]])

    def test_remainder_goes_to_last_page(self):
        self.assertEqual(
            pager.paginate(list("abcde"), 2),
            [["a", "b"], ["c", "d"], ["e"]])

    def test_per_page_one(self):
        self.assertEqual(pager.paginate(["a", "b"], 1), [["a"], ["b"]])

    def test_per_page_below_one_is_clamped(self):
        self.assertEqual(pager.paginate(["a", "b"], 0), [["a"], ["b"]])

    def test_matches_legacy_chunks_behavior(self):
        # 與被取代的 list(chunks(lst, n)) 完全一致
        def chunks(lst, n):
            for i in range(0, len(lst), n):
                yield lst[i:i + n]

        for total in range(0, 23):
            for per in range(1, 11):
                lst = list(range(total))
                self.assertEqual(
                    pager.paginate(lst, per), list(chunks(lst, per)),
                    "total=%d per=%d" % (total, per))


class PageCountTests(unittest.TestCase):
    def test_zero_candidates_zero_pages(self):
        self.assertEqual(pager.pageCount(0, 6), 0)

    def test_exact_and_remainder(self):
        self.assertEqual(pager.pageCount(12, 6), 2)
        self.assertEqual(pager.pageCount(13, 6), 3)

    def test_consistent_with_paginate(self):
        for total in range(0, 23):
            for per in range(1, 11):
                self.assertEqual(
                    pager.pageCount(total, per),
                    len(pager.paginate(list(range(total)), per)))


class ClampTests(unittest.TestCase):
    def test_dayi_capped_at_six(self):
        self.assertEqual(pager.maxCandPerPage("chedayi"), 6)
        self.assertEqual(pager.clampCandPerPage(9, "chedayi"), 6)

    def test_others_capped_at_ten(self):
        for ime in ("checj", "chearray", "cheliu", "chephonetic"):
            self.assertEqual(pager.maxCandPerPage(ime), 10)
        self.assertEqual(pager.clampCandPerPage(15, "checj"), 10)

    def test_lower_bound_is_one(self):
        self.assertEqual(pager.clampCandPerPage(0, "checj"), 1)
        self.assertEqual(pager.clampCandPerPage(-3, "chedayi"), 1)

    def test_in_range_passes_through(self):
        self.assertEqual(pager.clampCandPerPage(6, "chedayi"), 6)
        self.assertEqual(pager.clampCandPerPage(9, "checj"), 9)


if __name__ == "__main__":
    unittest.main()
