"""Static checks on the settings pages' HTML and JS (no browser, no server).

新酷音 (input_methods/chewing/config_tool.html + js/config.js): the classic
candidate window's 每列顯示候選字個數 (#candPerRow) and the 選字範例 preview
(#selExample, updateSelExample) did nothing for the current candidate window and
were removed, and 每頁候選字數 (#candPerPage) moved into the 候選窗外觀 number row
next to 每列候選字數. Another change that removed candPerRow its own way edits the
same lines, so merging the two conflicts there: keeping both sides of the HTML
gives two #candPerPage inputs sharing one id (the form posts both values), and
taking the other side of the JS brings back an updateSelExample() that nothing
calls, aimed at the removed #selExample.

大易/酷倉 (cinbase/config: the IME's config/config.html shell + config.htm
fragments + js/config.js): the page never had #candPerRow, #candPerPage,
#candMaxItems or #selExample, but config.js still set them up.
"""

import collections
import html.parser
import os
import re
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
PYTHON_DIR = os.path.join(ROOT, "python")
CHEWING_DIR = os.path.join(PYTHON_DIR, "input_methods", "chewing")
CINBASE_CONFIG_DIR = os.path.join(PYTHON_DIR, "cinbase", "config")

# fields of the classic candidate window that the pages no longer have
RETIRED_IDS = ("candPerRow", "candPerPage", "candMaxItems", "selExample")

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
         "source", "track", "wbr"}


class _PageIds(html.parser.HTMLParser):
    """Every id in a page, with the classes of the elements around it."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.open = []  # (tag, classes) of the open elements
        self.ids = []   # (id, classes of its ancestors)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.append((attrs["id"], {c for _, classes in self.open for c in classes}))
        if tag not in _VOID:
            self.open.append((tag, (attrs.get("class") or "").split()))

    def handle_endtag(self, tag):
        # close up to the matching tag, like a browser does for an unclosed <p>/<li>
        for i in range(len(self.open) - 1, -1, -1):
            if self.open[i][0] == tag:
                del self.open[i:]
                break


def page_ids(*paths):
    ids = []
    for path in paths:
        parser = _PageIds()
        with open(path, encoding="utf-8-sig") as f:
            parser.feed(f.read())
        parser.close()
        ids += parser.ids
    return ids


def script_lines(path, pattern):
    """(line number, text) of each line of a script that matches pattern."""
    with open(path, encoding="utf-8-sig") as f:
        return [(n, line.strip()) for n, line in enumerate(f, 1) if re.search(pattern, line)]


class ConfigPageTests(unittest.TestCase):
    maxDiff = None  # list every offending script line

    def assert_no_script_for_missing_fields(self, js_path, ids):
        names = {name for name, _ in ids}
        selectors = ["#%s\\b" % name for name in RETIRED_IDS if name not in names]
        pattern = "|".join(selectors + [r"\bupdateSelExample\b"])
        self.assertEqual(script_lines(js_path, pattern), [], os.path.relpath(js_path, ROOT))

    def test_chewing_ids_are_unique(self):
        ids = page_ids(os.path.join(CHEWING_DIR, "config_tool.html"))
        counts = collections.Counter(name for name, _ in ids)
        self.assertEqual([name for name, n in counts.items() if n > 1], [])

    def test_chewing_cand_per_page_is_in_the_candidate_window_number_row(self):
        ids = page_ids(os.path.join(CHEWING_DIR, "config_tool.html"))
        found = [classes for name, classes in ids if name == "candPerPage"]
        self.assertEqual(len(found), 1)
        self.assertIn("candidate-window-settings", found[0])
        self.assertIn("candidate-number-row", found[0])
        names = {name for name, _ in ids}
        self.assertNotIn("candPerRow", names)
        self.assertNotIn("selExample", names)

    def test_chewing_script_has_no_retired_fields(self):
        ids = page_ids(os.path.join(CHEWING_DIR, "config_tool.html"))
        self.assert_no_script_for_missing_fields(os.path.join(CHEWING_DIR, "js", "config.js"), ids)

    def test_cinbase_script_has_no_retired_fields(self):
        for ime in ("chedayi", "checj"):
            with self.subTest(ime=ime):
                ids = page_ids(os.path.join(PYTHON_DIR, "input_methods", ime, "config", "config.html"),
                               os.path.join(CINBASE_CONFIG_DIR, "config.htm"))
                self.assert_no_script_for_missing_fields(
                    os.path.join(CINBASE_CONFIG_DIR, "js", "config.js"), ids)


if __name__ == "__main__":
    unittest.main()
