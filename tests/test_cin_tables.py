"""Content checks on the code tables the limited installer ships
(the python\\cinbase\\json\\*.json files listed in installer/installer.nsi).

dayi3.cin (大易三碼, the default 大易 table) had six multi-character values
wrapped in ASCII double quotes under ;; (蟲) and 06: the table author's notes
"三碼", "無詞", "第５．０版", "八八八", "背杯ＯＡ專用" and "金門". Typing ;; for 蟲
listed them as candidates, and picking one committed the quotes too. ASCII-only
values such as the emoticon "<[+_+]>" in newcj are real candidates and stay.
"""

import json
import os
import re
import unittest

import cinbase_harness as h

INSTALLER = os.path.join(h.ROOT, "installer", "installer.nsi")


def shipped_tables():
    with open(INSTALLER, encoding="utf-8-sig") as f:
        names = re.findall(r'File "\.\.\\python\\cinbase\\json\\([^"\\]+\.json)"', f.read())
    return sorted(set(names))


def quote_wrapped(value):
    """A value in .cin quotes around non-ASCII text: cin syntax, not a candidate."""
    return len(value) > 2 and value[0] == value[-1] == '"' and not value.isascii()


class ShippedTableTests(unittest.TestCase):
    def test_installer_list_is_found(self):
        tables = shipped_tables()
        for name in ("dayi3.json", "dayi4.json", "thdayi.json", "checj.json"):
            self.assertIn(name, tables)

    @unittest.skipUnless(all(os.path.exists(os.path.join(h.JSON_DIR, name)) for name in shipped_tables()),
                         "cinbase/json tables not generated (run python/cinbase/tools/cintojson.py)")
    def test_no_quoted_candidates(self):
        for name in shipped_tables():
            with self.subTest(table=name):
                with open(os.path.join(h.JSON_DIR, name), encoding="utf-8") as f:
                    chardefs = json.load(f)["chardefs"]
                quoted = [(key, value) for key, values in chardefs.items()
                          for value in values if quote_wrapped(value)]
                self.assertEqual(quoted, [])

    @h.requires_tables
    def test_dayi3_codes_that_had_notes(self):
        with open(os.path.join(h.JSON_DIR, "dayi3.json"), encoding="utf-8") as f:
            chardefs = json.load(f)["chardefs"]
        self.assertEqual(chardefs[";;"], ["蟲"])
        self.assertIn("鍆", chardefs["06"])
        for key in (";;", "06"):
            self.assertFalse(any('"' in value for value in chardefs[key]), key)


if __name__ == "__main__":
    unittest.main()
