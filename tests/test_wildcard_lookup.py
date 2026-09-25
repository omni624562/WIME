"""The wildcard lookup narrows the keys it matches (keys grouped by length, a
binary search on the literal prefix, a per-position index when the pattern
starts with a wildcard) instead of running the regex over the whole table on
every key. It must return exactly what the old full scan returned, in the same
order: the candidate order is what the user sees and learns.
"""

import io
import os
import random
import re
import unittest

import cinbase_harness as h

TABLES = ("checj.json", "thcj.json", "thdayi.json", "dayi3.json")


def setUpModule():
    global _appdata
    _appdata = h.IsolatedAppData()


def tearDownModule():
    _appdata.close()


def load(name):
    with open(os.path.join(h.JSON_DIR, name), encoding="utf-8") as f:
        return h.cinbase.Cin(f, "wildcard_test", True)


def full_scan(cin, composition, wildcard, variable):
    """The matching the lookup used before: every sorted key through the regex."""
    pattern = re.compile("^" + "".join(("(.*)" if variable else "(.)") if c == wildcard else re.escape(c)
                                       for c in composition) + "$")
    return [key for key in cin.sortedCharDefKeys()
            if (variable or len(key) == len(composition)) and pattern.match(key)]


def sample_patterns(cin, rng, count=150):
    """Wildcard patterns made from real keys (so most match), plus some that don't."""
    keys = [key for key in cin.sortedCharDefKeys() if len(key) >= 2]
    roots = sorted({c for key in keys for c in key})
    patterns = set()
    for key in rng.sample(keys, count):
        positions = rng.sample(range(len(key)), rng.randint(1, len(key)))
        patterns.add("".join("*" if i in positions else c for i, c in enumerate(key)))
    for _ in range(count // 3):        # random, mostly without matches
        length = rng.randint(2, 5)
        chars = [rng.choice(roots) for _ in range(length)]
        chars[rng.randrange(length)] = "*"
        patterns.add("".join(chars))
    patterns.update({"*", "**", "***", "*" + roots[0], roots[0] + "*", "*" + roots[-1] * 3})
    return sorted(patterns)


def variable_patterns(cin, rng, count=60):
    """大易's variable form: one * in the middle, e.g. a*b matches ab, axb, axyb."""
    keys = [key for key in cin.sortedCharDefKeys() if len(key) >= 3]
    patterns = set()
    for key in rng.sample(keys, count):
        cut = rng.randint(1, len(key) - 1)
        end = rng.randint(cut, len(key) - 1)
        patterns.add(key[:cut] + "*" + key[end:])
    return sorted(patterns)


@h.requires_tables
class SameResultsAsFullScanTests(unittest.TestCase):
    def test_fixed_length_patterns(self):
        rng = random.Random(20260925)
        for name in TABLES:
            if not os.path.exists(os.path.join(h.JSON_DIR, name)):
                continue
            cin = load(name)
            try:
                for composition in sample_patterns(cin, rng):
                    pattern = re.compile("^" + "".join("(.)" if c == "*" else re.escape(c) for c in composition) + "$")
                    self.assertEqual(cin._wildcardMatchKeys(composition, "*", pattern, False),
                                     full_scan(cin, composition, "*", False), (name, composition))
            finally:
                cin.__del__()

    def test_variable_length_patterns(self):
        rng = random.Random(7)
        for name in ("thdayi.json", "dayi3.json"):
            cin = load(name)
            try:
                for composition in variable_patterns(cin, rng):
                    pattern = re.compile("^" + "".join("(.*)" if c == "*" else re.escape(c) for c in composition) + "$")
                    self.assertEqual(cin._wildcardMatchKeys(composition, "*", pattern, True),
                                     full_scan(cin, composition, "*", True), (name, composition))
            finally:
                cin.__del__()

    def test_z_as_the_wildcard_character(self):
        # selWildcardType 0 uses z, which is also an ordinary root in some tables
        cin = load("checj.json")
        try:
            for composition in ("hz", "zh", "zz", "azb", "zzz", "yzz"):
                pattern = re.compile("^" + "".join("(.)" if c == "z" else re.escape(c) for c in composition) + "$")
                self.assertEqual(cin._wildcardMatchKeys(composition, "z", pattern, False),
                                 full_scan(cin, composition, "z", False), composition)
        finally:
            cin.__del__()


class ResultCacheTests(unittest.TestCase):
    def table(self):
        data = '{"chardefs": {"ab": ["甲"], "ac": ["乙", "甲"], "bc": ["丙"]}, "keynames": {}}'
        return h.cinbase.Cin(io.StringIO(data), "wildcard_test", False)

    def test_callers_cannot_change_the_cached_result(self):
        cin = self.table()
        first = cin.getWildcardCharDefs("a*", "*", 100)
        self.assertEqual(first, ["甲", "乙"])
        first.append("丁")
        self.assertEqual(cin.getWildcardCharDefs("a*", "*", 100), ["甲", "乙"])

    def test_extend_table_invalidates_the_cache(self):
        cin = self.table()
        self.assertEqual(cin.getWildcardCharDefs("a*", "*", 100), ["甲", "乙"])
        extend = h.cinbase.extendtable(["ab 丁"])
        # priority insertion changes the candidates of an existing key only
        cin.updateCinTable(True, True, extend, False)
        self.assertEqual(cin.getWildcardCharDefs("a*", "*", 100), ["丁", "甲", "乙"])
        extend = h.cinbase.extendtable(["ad 戊"])
        cin.updateCinTable(True, False, extend, False)      # a new key
        self.assertEqual(cin.getWildcardCharDefs("a*", "*", 100), ["丁", "甲", "乙", "戊"])

    def test_the_cache_is_bounded(self):
        cin = self.table()
        for i in range(cin.WILDCARD_CACHE_SIZE + 10):
            cin.getWildcardCharDefs("a*", "*", i + 1)
        self.assertLessEqual(len(cin._wildcard_results), cin.WILDCARD_CACHE_SIZE)


if __name__ == "__main__":
    unittest.main()
