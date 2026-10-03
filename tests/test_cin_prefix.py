"""Cin.isCharDefPrefix / hasLongerCharDefPrefix (python/cinbase/cin.py).

They used to build a set of every prefix of every code the first time an
unfinished code was typed (a 40 ms / 100 ms stall in 大易 / 酷倉 and 2–4 MB);
they now binary-search the sorted code list. Compare them with the obvious
set-based definition on the real tables.
"""

import os
import random
import unittest

import cinbase_harness as h
from cinbase.cin import Cin

TABLES = ("dayi4.json", "thdayi.json", "checj.json")


def setUpModule():
    global _appdata
    _appdata = h.IsolatedAppData()  # Cin loads/saves the selection counts under APPDATA


def tearDownModule():
    _appdata.close()


@h.requires_tables
class PrefixLookupTests(unittest.TestCase):
    def check_table(self, name):
        with open(os.path.join(h.JSON_DIR, name), encoding="utf-8") as f:
            table = Cin(f, name[:-5], True)
        try:
            keys = list(table.chardefs)
            prefixes, proper = set(), set()
            for key in keys:
                for n in range(1, len(key) + 1):
                    prefixes.add(key[:n])
                for n in range(1, len(key)):
                    proper.add(key[:n])
            rng = random.Random(name)
            alphabet = sorted({ch for key in keys for ch in key})
            probes = prefixes | {"".join(rng.choice(alphabet) for _ in range(rng.randint(1, 6)))
                                 for _ in range(5000)} | {""}
            wrong = [p for p in probes
                     if table.isCharDefPrefix(p) != (p in prefixes)
                     or table.hasLongerCharDefPrefix(p) != (p in proper)]
            self.assertEqual(wrong, [])
        finally:
            table.__del__()

    def test_prefix_lookups_match_the_set_definition(self):
        for name in TABLES:
            with self.subTest(table=name):
                self.check_table(name)


if __name__ == "__main__":
    unittest.main()
