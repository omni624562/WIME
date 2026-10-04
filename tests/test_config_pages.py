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

大易/酷倉 text data (js/data_format.js, run in node when it is installed): the
page refused data the backend reads fine. A blank line (a trailing newline), a
UTF-8 BOM or an empty 簡易符號 box in any text tab blocked 套用設定 for every
option, and 擴展碼表 codes had to be letters and digits, so the 大易 codes that
use the , . / ; ' [ ] - = \\ ` roots (about a quarter of them) could not be added.
"""

import ast
import collections
import glob
import html.parser
import json
import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
PYTHON_DIR = os.path.join(ROOT, "python")
CHEWING_DIR = os.path.join(PYTHON_DIR, "input_methods", "chewing")
CINBASE_CONFIG_DIR = os.path.join(PYTHON_DIR, "cinbase", "config")
CIN_JSON_DIR = os.path.join(PYTHON_DIR, "cinbase", "json")
DATA_FORMAT_JS = os.path.join(CINBASE_CONFIG_DIR, "js", "data_format.js")
NODE = shutil.which("node")

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


def function_body(path, name):
    """Source of `function name(...) {` up to the closing brace at the same indentation."""
    with open(path, encoding="utf-8-sig") as f:
        source = f.read()
    match = re.search(r"^([ \t]*)function %s\(.*?\{\n(.*?)^\1\}" % re.escape(name), source, re.M | re.S)
    if not match:
        raise AssertionError("function %s not found in %s" % (name, os.path.relpath(path, ROOT)))
    return match.group(2)


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

    def test_cinbase_has_the_shift_space_option(self):
        # 大易/酷倉 always took Shift+Space for 全形/半形 with no way to turn it off;
        # the option has the same key and wording as 新酷音's
        with open(os.path.join(CINBASE_CONFIG_DIR, "config.htm"), encoding="utf-8-sig") as f:
            page = f.read()
        typing = page[page.index('<div id="typing_page">'):page.index('<div id="intelligent_page">')]
        card = typing[typing.index('<h3 class="card-title">行為設定</h3>'):]
        card = card[:card.index('<div class="card">')]
        # updateConfig() saves every named checkbox under its name; pageReady() sets it by id
        self.assertIn('<input type="checkbox" id="enableShiftSpace" name="enableShiftSpace" />', card)
        self.assertIn('<label for="enableShiftSpace">使用 Shift+空白鍵切換全形/半形</label>', card)
        self.assertRegex(card, r'<label for="enableShiftSpace">[^<]*</label>\s*<div class="setting-hint">')
        self.assertEqual([name for name, _ in page_ids(os.path.join(CINBASE_CONFIG_DIR, "config.htm"))
                          if name == "enableShiftSpace"], ["enableShiftSpace"])

        # checked when config.json has no such key, for every CIN IME (before the
        # modern-window-only defaults return early)
        defaults = function_body(os.path.join(CINBASE_CONFIG_DIR, "js", "config.js"), "applyCandidateDefaults")
        match = re.search(r'if \(typeof checjConfig\.enableShiftSpace === "undefined"\) \{\s*'
                          r'checjConfig\.enableShiftSpace = true;\s*\}', defaults)
        self.assertIsNotNone(match)
        self.assertLess(match.start(), defaults.index("if (!modernDefaultIme)"))

    def test_pages_mark_the_max_width_as_migrated_on_save(self):
        # The backend replaces a stored candidateMaxWidth of 300 (the old default)
        # with the new default unless this marker is set, so a 300 picked on the
        # page came back as 320/340. Every save from either page sets it.
        for path, config in ((os.path.join(CINBASE_CONFIG_DIR, "js", "config.js"), "checjConfig"),
                             (os.path.join(CHEWING_DIR, "js", "config.js"), "chewingConfig")):
            with self.subTest(page=os.path.relpath(path, ROOT)):
                body = function_body(path, "saveConfig")
                indent = re.match(r"(?:[ \t]*\n)*([ \t]*)\S", body).group(1)
                # unconditional: at the function body's own indentation, before the request is built
                match = re.search(r"^%s%s\.candidateMaxWidthMigrated = true;$" % (indent, config), body, re.M)
                self.assertIsNotNone(match)
                self.assertRegex(body, r'"?config"?: %s\b' % config)
                self.assertLess(match.start(), body.index("JSON.stringify(data)"))

    def test_cinbase_pages_load_the_data_format_rules(self):
        # checkDataFormat() in js/config.js calls findDataFormatError(); without the
        # script every 套用設定 that changed a text tab would throw and save nothing
        pages = sorted(glob.glob(os.path.join(PYTHON_DIR, "input_methods", "*", "config", "config.html")))
        self.assertGreaterEqual(len(pages), 2)
        for page in pages:
            with self.subTest(page=os.path.relpath(page, ROOT)):
                with open(page, encoding="utf-8-sig") as f:
                    scripts = re.findall(r'<script[^>]*\bsrc="([^"]+)"', f.read())
                self.assertIn("js/data_format.js", scripts)
                self.assertLess(scripts.index("js/data_format.js"), scripts.index("config.js"))


def extend_table_code_keys():
    """extendTableCodeKeys from js/data_format.js: {IME folder: allowed code characters}."""
    with open(DATA_FORMAT_JS, encoding="utf-8-sig") as f:
        body = re.search(r"var extendTableCodeKeys = \{(.*?)\};", f.read(), re.S).group(1)
    return {name: json.loads(value)
            for name, value in re.findall(r'"(\w+)":\s*("(?:[^"\\]|\\.)*")', body)}


def cin_file_list(ime):
    """CIN_FILE_LIST of an input_methods/<ime>/<ime>_ime.py, read without importing it."""
    with open(os.path.join(PYTHON_DIR, "input_methods", ime, ime + "_ime.py"), encoding="utf-8-sig") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and getattr(node.targets[0], "id", None) == "CIN_FILE_LIST"):
            return ast.literal_eval(node.value)
    return []


class ExtendTableCodeKeysTests(unittest.TestCase):
    """The 擴展碼表 check accepts exactly the keys of the IME's tables (%keyname)."""

    def test_keys_are_the_union_of_the_table_keynames(self):
        declared = extend_table_code_keys()
        self.assertIn("chedayi", declared)
        self.assertIn("checj", declared)
        checked = 0
        for ime_py in sorted(glob.glob(os.path.join(PYTHON_DIR, "input_methods", "*", "*_ime.py"))):
            ime = os.path.basename(os.path.dirname(ime_py))
            tables = [name for name in cin_file_list(ime) if os.path.exists(os.path.join(CIN_JSON_DIR, name))]
            if not tables:
                continue  # not a CIN IME, or its tables are not generated here
            keys = set()
            for name in tables:
                with open(os.path.join(CIN_JSON_DIR, name), encoding="utf-8") as f:
                    keys.update(key.lower() for key in json.load(f)["keynames"])
            with self.subTest(ime=ime):
                self.assertIn(ime, declared, "add the keys of %s's tables to extendTableCodeKeys" % ime)
                # a key missing here makes real codes unsavable; an extra one lets a dead code through
                self.assertEqual("".join(sorted(set(declared[ime]))), "".join(sorted(keys)))
                checked += 1
        if not checked:
            self.skipTest("cinbase/json tables not generated (run python/cinbase/tools/cintojson.py)")


@unittest.skipUnless(NODE, "node is not installed")
class DataFormatRuleTests(unittest.TestCase):
    """findDataFormatError() from js/data_format.js, run in node."""

    RUNNER = r"""
const fs = require("fs"), vm = require("vm");
const sandbox = {};
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8").replace(/^﻿/, ""), sandbox);
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(cases.map(c => sandbox.findDataFormatError(c[0], c[1], c[2]))));
"""

    def errors(self, cases):
        """[(text, type, ime)] -> [None or (line index, line text)]"""
        result = subprocess.run([NODE, "-e", self.RUNNER, DATA_FORMAT_JS], input=json.dumps(cases),
                                capture_output=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [error and (error["line"], error["text"]) for error in json.loads(result.stdout)]

    def assert_valid(self, type_, texts, ime="chedayi"):
        self.assertEqual(self.errors([[text, type_, ime] for text in texts]), [None] * len(texts))

    def test_blank_lines_bom_and_surrounding_spaces_are_ignored(self):
        for type_, line in (("1", "a 符號"), ("2", "標點=，。"), ("3", "ab 一")):
            with self.subTest(type=type_):
                self.assert_valid(type_, [
                    "",                                  # an empty box (簡易符號 used to refuse it)
                    line + "\n",                         # file ending in a newline
                    line + "\n\n" + line,                # blank line in the middle
                    "﻿" + line + "\n" + line,       # Notepad's UTF-8 BOM
                    "  " + line + "\t\n \t\n" + line,    # whitespace-only line, indentation
                ])

    def test_dayi_codes_with_punctuation_roots_are_accepted(self):
        self.assert_valid("3", [",,z 測試", "a/ 詞", "/;a\t分隔", "[1 詞", "'-=\\` 詞", "AB 大寫", ".. " + "長" * 41])

    def test_malformed_extend_table_lines_point_at_the_line(self):
        cases = [
            ["ab 一\ncd", "3", "chedayi"],             # no separator
            ["ab 一\n\n測 試", "3", "chedayi"],         # not a key of any 大易 table
            ["ab 一\nx! 詞", "3", "chedayi"],           # ! is not a 大易 root
            ["ab\t一 二", "3", "chedayi"],              # split at the space like the backend: code "ab\t一"
            ["abc 酷\na1 詞", "3", "checj"],            # 倉頡 tables have no digit keys
            ["a! 詞\n測 試", "3", "cheliu"],            # no tables listed: printable ASCII only
        ]
        self.assertEqual(self.errors(cases),
                         [(1, "cd"), (2, "測 試"), (1, "x! 詞"), (0, "ab\t一 二"), (1, "a1 詞"), (1, "測 試")])

    def test_malformed_easy_symbol_and_list_lines_point_at_the_line(self):
        cases = [
            ["a 一\n1 一", "1", "chedayi"],
            ["a 一\nab 一", "1", "chedayi"],
            ["a 一二三四五六七八九十\nb 一二三四五六七八九十一", "1", "chedayi"],  # at most 10 characters
            ["a=b\n\nxy", "2", "chedayi"],
        ]
        self.assertEqual(self.errors(cases), [(1, "1 一"), (1, "ab 一"), (1, "b 一二三四五六七八九十一"), (2, "xy")])

    def test_single_symbol_lines_count_code_points(self):
        self.assert_valid("2", ["★", "😀", "𠀀\n標點=，。"])


if __name__ == "__main__":
    unittest.main()
