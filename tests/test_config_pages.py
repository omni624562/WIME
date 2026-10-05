"""Static checks on the settings pages' HTML and JS (no browser, no server).

新酷音 (input_methods/chewing/config_tool.html + js/config.js): the classic
candidate window's 每列顯示候選字個數 (#candPerRow) and the 選字範例 preview
(#selExample, updateSelExample) did nothing for the current candidate window and
were removed, and 每頁候選字數 (#candPerPage) moved into the 候選窗外觀 number row
next to 每列候選字數. Another change that removed candPerRow its own way edits the
same lines, so merging the two conflicts there: keeping both sides of the HTML
gives two #candPerPage inputs sharing one id (the form posts both values), and
taking the other side of the JS brings back an updateSelExample() that nothing
calls, aimed at the removed #selExample. 按住 Shift：輸出英文大寫字母 did
nothing while 按住 Shift 快速輸入符號 was on, which is the default; it is
disabled then, with a hint.

大易/酷倉 (cinbase/config: the IME's config/config.html shell + config.htm
fragments + js/config.js): the page never had #candPerRow, #candPerPage,
#candMaxItems or #selExample, but config.js still set them up.

大易/酷倉 智慧選字: the hints described frequency and recency ranking, but it
only moves a character up after a previous character it followed before.

大易/酷倉 text data (js/data_format.js, run in node when it is installed): the
page refused data the backend reads fine. A blank line (a trailing newline), a
UTF-8 BOM or an empty 簡易符號 box in any text tab blocked 套用設定 for every
option, and 擴展碼表 codes had to be letters and digits, so the 大易 codes that
use the , . / ; ' [ ] - = \\ ` roots (about a quarter of them) could not be added.
Lengths are counted in the symbols the backend splits the files into
(cinbase/textclusters.py), not in UTF-16 units or code points: a line holding
only ❤️ or 🇹🇼, or a 簡易符號 of six Ext-B characters, was refused.
saveConfig() (run in node with a jQuery stub) checks only the text tabs it
posts, the ones changed this time, so a line the page refuses in a file edited
by hand no longer blocks saving the other options.
"""

import ast
import collections
import glob
import html.parser
import importlib.util
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
TEXTCLUSTERS_PY = os.path.join(PYTHON_DIR, "cinbase", "textclusters.py")
NODE = shutil.which("node")

# fields of the classic candidate window that the pages no longer have
RETIRED_IDS = ("candPerRow", "candPerPage", "candMaxItems", "selExample")

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
         "source", "track", "wbr"}


class _PageIds(html.parser.HTMLParser):
    """Every id in a page, with the classes of the elements around it."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.open = []     # (tag, classes, id) of the open elements
        self.ids = []      # (id, classes of its ancestors)
        self.parents = {}  # id -> ids of its ancestors, outermost first

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.append((attrs["id"], {c for _, classes, _ in self.open for c in classes}))
            self.parents[attrs["id"]] = [parent for _, _, parent in self.open if parent]
        if tag not in _VOID:
            self.open.append((tag, (attrs.get("class") or "").split(), attrs.get("id")))

    def handle_endtag(self, tag):
        # close up to the matching tag, like a browser does for an unclosed <p>/<li>
        for i in range(len(self.open) - 1, -1, -1):
            if self.open[i][0] == tag:
                del self.open[i:]
                break


def parse_page(path):
    parser = _PageIds()
    with open(path, encoding="utf-8-sig") as f:
        parser.feed(f.read())
    parser.close()
    return parser


def page_ids(*paths):
    ids = []
    for path in paths:
        ids += parse_page(path).ids
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

    def test_chewing_upper_case_with_shift_follows_easy_symbols(self):
        # While 中文模式下按住 Shift 快速輸入符號 is on, Shift+letter always types the
        # 簡易符號 (chewing_ime.py reads upperCaseWithShift only when it is off), so the
        # 輸出英文大寫字母 checkbox looked active and changed nothing
        with open(os.path.join(CHEWING_DIR, "config_tool.html"), encoding="utf-8-sig") as f:
            page = f.read()
        self.assertRegex(page, r'for="upperCaseWithShift">[^<]*</label>\s*'
                               r'<div class="setting-hint">[^<]*快速輸入符號[^<]*沒有作用')
        script = os.path.join(CHEWING_DIR, "js", "config.js")
        self.assertRegex(function_body(script, "updateUpperCaseWithShift"),
                         r'\$\("#upperCaseWithShift"\)\.prop\("disabled", \$\("#easySymbolsWithShift"\)\.prop\("checked"\)\);')
        init = function_body(script, "initializeUI")
        # when the page loads, and whenever the other box is toggled
        self.assertRegex(init, r"(?m)^\s*updateUpperCaseWithShift\(\);$")
        self.assertRegex(init, r'\$\("#easySymbolsWithShift"\)\.on\("click", updateUpperCaseWithShift\);')
        # a disabled checkbox is still saved with its value
        self.assertNotRegex(function_body(script, "updateConfig"), r"disabled")

    def test_chewing_page_offers_only_message_options_that_work(self):
        # 提示強度行為 (candidateMessageBehavior) changed nothing in 新酷音: only 大易/酷倉
        # show a message while typing, and 新酷音's messages (加入：…) all come after
        # a confirmation, in the 提示訊息樣式 style. The preview showed 查無組字, a
        # 大易/酷倉 message 新酷音 never shows.
        names = {name for name, _ in page_ids(os.path.join(CHEWING_DIR, "config_tool.html"))}
        self.assertEqual({name for name in names if "MessageBehavior" in name}, set())
        script = os.path.join(CHEWING_DIR, "js", "config.js")
        # dropped from an old config.json before saving, never set or shown
        self.assertEqual([line for _, line in script_lines(script, r"MessageBehavior|behavior-")],
                         ["delete chewingConfig.candidateMessageBehavior;"])
        with open(os.path.join(CHEWING_DIR, "chewing_ime.py"), encoding="utf-8-sig") as f:
            self.assertNotIn("candidateMessageBehavior", f.read())
        preview = function_body(script, "createCandidateMessagePreview")
        self.assertIn('.text("加入：你好")', preview)
        self.assertNotIn('"查無組字"', preview)

    def test_chewing_about_dialog_links(self):
        # the 龔律全 page answers 403, the 陳康本 Google+ profile redirects to a Google
        # blog post, and the ICOS 2004 slides are a Flash file no browser plays
        with open(os.path.join(CHEWING_DIR, "config_tool.html"), encoding="utf-8-sig") as f:
            page = f.read()
        about = page[page.index('id="about_modal"'):page.index('<div class="tab-content">')]
        links = re.findall(r'<a href="([^"]*)"', about)
        self.assertIn("https://chewing.im/doc/chewing-report.pdf", links)
        for url in links:
            self.assertTrue(url.startswith("https://"), url)
        for dead in ("~b6506053", "plus.google.com", "chewing-intro.html", "Flash）</a>"):
            self.assertNotIn(dead, about)

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

    def test_cinbase_smart_select_hints_describe_context_prediction(self):
        # 智慧選字 ranks only by the previous character (cin.py sortByCount(),
        # tests/test_smartselect_spec.py); the hints described frequency and recency
        # ranking, which it never does. 近期選字優先 only orders the characters a
        # previous character already picked, so it is off whenever 前一字上下文 is.
        with open(os.path.join(CINBASE_CONFIG_DIR, "config.htm"), encoding="utf-8-sig") as f:
            page = f.read()
        hints = dict((name, (label, hint)) for name, label, hint in re.findall(
            r'<label for="(\w+)">([^<]*)</label>\s*<div class="setting-hint">([^<]*)</div>', page))

        label, hint = hints["intelligentSelect"]
        self.assertEqual(label, "智慧選字")
        self.assertIn("在同一個前一字之後選過的字", hint)
        self.assertIn("沒有前一字的紀錄時不改變順序", hint)
        label, hint = hints["intelligentSelectContext"]
        self.assertEqual(label, "前一字上下文")  # the ` menu's 「智慧選字：前一字上下文」
        self.assertIn("關閉時智慧選字不改變候選順序", hint)
        self.assertIn("仍會記錄選字", hint)      # addIntelligentSelectCount() checks intelligentSelect only
        label, hint = hints["intelligentSelectRecent"]
        self.assertEqual(label, "近期選字優先")
        self.assertIn("同一個前一字之後選過好幾個字時", hint)
        self.assertIn("需開啟「前一字上下文」", hint)
        # sortByPhrase() moves what follows the previous character in the phrase table
        self.assertIn("能和前一個字組成聯想字詞的字", hints["sortByPhrase"][1])
        smart = "".join(label + hint for name, (label, hint) in hints.items() if name.startswith("intelligentSelect"))
        for old in ("常用字排到", "使用習慣", "最近選過的字會優先出現", "加權"):
            self.assertNotIn(old, smart)
        self.assertLess(page.index('id="intelligentSelectContext_item"'), page.index('id="intelligentSelectRecent_item"'))

        script = os.path.join(CINBASE_CONFIG_DIR, "js", "config.js")
        bindings = re.findall(r'bindDependentEnable\(([^,\[]+|\[[^\]]*\]), \[\s*(.*?)\s*\]\);',
                              function_body(script, "pageReady"), re.S)
        parents = {field: re.findall(r'"(\w+)"', parent)
                   for parent, dependents in bindings for field in re.findall(r'field: "(\w+)"', dependents)}
        self.assertEqual(parents["intelligentSelectContext"], ["intelligentSelect"])
        self.assertEqual(parents["intelligentSelectRecent"], ["intelligentSelect", "intelligentSelectContext"])

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

    def test_pages_always_save_the_fixed_candidate_styles(self):
        # 選字符 Word First and (大易/酷倉) 名稱標籤 Accent are the only styles left,
        # and the theme/message previews draw them. The page must save exactly those,
        # whatever an older config.json held (the backends still default to
        # keycap/badge), or the window would not look like the preview.
        pages = (
            (os.path.join(CINBASE_CONFIG_DIR, "js", "config.js"), "checjConfig",
             os.path.join(CINBASE_CONFIG_DIR, "config.htm"),
             os.path.join(CINBASE_CONFIG_DIR, "js", "candidate_appearance.js"),
             {"candidateKeyStyle": "word-first", "candidateHeaderStyle": "accent"}),
            (os.path.join(CHEWING_DIR, "js", "config.js"), "chewingConfig",
             os.path.join(CHEWING_DIR, "config_tool.html"),
             os.path.join(CHEWING_DIR, "js", "candidate_appearance.js"),
             {"candidateKeyStyle": "word-first"}),
        )
        for script, config, page, appearance, fixed in pages:
            defaults = function_body(script, "applyCandidateDefaults")
            indent = re.match(r"(?:[ \t]*\n)*([ \t]*)\S", defaults).group(1)
            with open(page, encoding="utf-8-sig") as f:
                html = f.read()
            with open(appearance, encoding="utf-8-sig") as f:
                options = f.read()
            for key, value in fixed.items():
                with self.subTest(page=os.path.relpath(script, ROOT), key=key):
                    # forced on load, unconditionally (not only when the key is missing)
                    self.assertRegex(defaults, r'(?m)^%s%s\.%s = "%s";$' % (indent, config, key, value))
                    # carried by a named hidden input, which updateConfig() saves
                    self.assertRegex(html, r'<input type="hidden" id="%s" name="%s"' % (key, key))
                    # the input is only ever set from the forced config or from a style
                    # card, and the only card left is the fixed style
                    writers = [line for _, line in script_lines(script, r'"#%s"\)\.val\([^)]' % key)]
                    self.assertTrue(writers)
                    for line in writers:
                        self.assertRegex(line, r'\.val\((%s\.%s \|\| "%s"|\$\(this\)\.data\("style"\))\);'
                                         % (config, key, value))
                    option_map = re.search(r"var %sOptions = \{(.*?)\};" % key, options, re.S)
                    self.assertIsNotNone(option_map)
                    self.assertEqual(re.findall(r'"?([\w-]+)"?\s*:', option_map.group(1)), [value])
            if "candidateHeaderStyle" in fixed:
                # before the modern-window-only defaults return early: every CIN IME
                self.assertLess(defaults.index('candidateHeaderStyle = "accent"'),
                                defaults.index("if (!modernDefaultIme)"))

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


def chars(codes):
    """'2764 FE0F' -> ❤️. Written as code points: most of these combine or are invisible."""
    return "".join(chr(int(code, 16)) for code in codes.split())


def backend_symbol_clusters():
    """symbolClusters() of cinbase/textclusters.py, loaded by itself (the package imports the whole IME)."""
    spec = importlib.util.spec_from_file_location("_textclusters", TEXTCLUSTERS_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.symbolClusters


# one symbol each for the backend, but more than one code point
MULTI_CODE_POINT_SYMBOLS = (
    "2764 FE0F",                                # ❤️: VS16
    "1F1F9 1F1FC",                              # 🇹🇼: two regional indicators
    "1F44D 1F3FB",                              # 👍🏻: skin tone
    "31 FE0F 20E3",                             # 1️⃣: keycap
    "1F468 200D 1F469 200D 1F467",              # 👨‍👩‍👧: ZWJ sequence
)

CLUSTER_SAMPLES = MULTI_CODE_POINT_SYMBOLS + (
    "2605 41 6A19",                             # ★, A, 標
    "1F600 20000",                              # 😀 and an Ext-B character: two UTF-16 units each
    "1F3F4 E0067 E0062 E0065 E006E E0067 E007F",  # England's flag: tag characters
    "1F1F9 1F1FC 1F1EF 1F1F5 1F1FA",            # two flags and a lone regional indicator
    "8FBB E0100",                               # 辻 with an ideographic variation selector
    "65 301 915 93F",                           # e + U+0301 (Mn), क + U+093F (Mc)
    "301 61 200D",                              # a mark with nothing before it, a trailing ZWJ
    "200D 61 62",                               # a leading ZWJ
)


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
    """findDataFormatError() and symbolClusters() from js/data_format.js, run in node."""

    RUNNER = r"""
const fs = require("fs"), vm = require("vm");
const sandbox = {}, call = process.argv[2];
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8").replace(/^\uFEFF/, ""), sandbox);
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(cases.map(args => sandbox[call](...args))));
"""

    def call(self, function, cases):
        """function(*args) in node for each args in cases"""
        result = subprocess.run([NODE, "-e", self.RUNNER, DATA_FORMAT_JS, function], input=json.dumps(cases),
                                capture_output=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def errors(self, cases):
        """[(text, type, ime)] -> [None or (line index, line text)]"""
        return [error and (error["line"], error["text"]) for error in self.call("findDataFormatError", cases)]

    def assert_valid(self, type_, texts, ime="chedayi"):
        self.assertEqual(self.errors([[text, type_, ime] for text in texts]), [None] * len(texts))

    def test_blank_lines_bom_and_surrounding_spaces_are_ignored(self):
        for type_, line in (("1", "a 符號"), ("2", "標點=，。"), ("3", "ab 一")):
            with self.subTest(type=type_):
                self.assert_valid(type_, [
                    "",                                  # an empty box (簡易符號 used to refuse it)
                    line + "\n",                         # file ending in a newline
                    line + "\n\n" + line,                # blank line in the middle
                    chars("FEFF") + line + "\n" + line,  # Notepad's UTF-8 BOM
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

    def test_single_symbol_lines_count_symbols(self):
        # symbols.py, fsymbols.py and flangs.py read each of these lines as one symbol
        # for the top-level menu, like ★
        self.assert_valid("2", ["★", chars("1F600"), chars("20000") + "\n標點=，。"]
                          + [chars(codes) for codes in MULTI_CODE_POINT_SYMBOLS])
        cases = [[text, "2", "chedayi"] for text in ("ab", chars("1F1F9 1F1FC 1F1EF 1F1F5"), chars("2764 FE0F 2605"))]
        self.assertEqual([error and error[0] for error in self.errors(cases)], [0, 0, 0])

    def test_easy_symbols_are_counted_in_symbols(self):
        # 「符號最多 10 個字」: six Ext-B characters or emoji are twelve UTF-16 units
        self.assert_valid("1", ["a " + chars("20000 20001 20002 20003 20004 20005"),
                                "a " + chars("1F600 1F601 1F602 1F603 1F604 1F605"),
                                "a " + chars("2764 FE0F") * 10])
        cases = [["a " + chars("20000") * 11, "1", "chedayi"], ["a " + chars("2764 FE0F") * 11, "1", "chedayi"]]
        self.assertEqual([error and error[0] for error in self.errors(cases)], [0, 0])

    def test_symbol_clusters_match_the_backend(self):
        # the page counts what cinbase/textclusters.py splits the symbol files into
        backend = backend_symbol_clusters()
        texts = [chars(codes) for codes in CLUSTER_SAMPLES]
        self.assertEqual(self.call("symbolClusters", [[text] for text in texts]),
                         [backend(text) for text in texts])


@unittest.skipUnless(NODE, "node is not installed")
class SaveConfigTextDataTests(unittest.TestCase):
    """saveConfig() and checkDataFormat() of the 大易/酷倉 page's js/config.js, run in node
    against a minimal jQuery stub (the page's scripts, in the page's order).

    Only the text tabs changed this time are posted, so only they are checked: a line
    the page refuses in a file edited by hand must not keep 主題、字型 and the other
    options from being saved. A refused line names its tab and line, switches to that
    tab and selects the line, again after the alert closes.
    """

    # textarea id, its *Changed flag minus "Changed" (also the posted key), rule type, name in the alert
    TEXT_TABS = (
        ("symbols", "symbols", "2", "特殊符號"),
        ("ez_symbols", "swkb", "1", "簡易符號"),
        ("fs_symbols", "fsymbols", "2", "全形標點符號"),
        ("phrase", "phrase", "2", "聯想字詞"),
        ("excludePhrase", "excludePhrase", "2", "排除聯想字詞"),
        ("flangs", "flangs", "2", "外語文字"),
        ("extendtable", "extendtable", "3", "擴展碼表"),
    )
    VALID = {"1": "a 一\n", "2": "標點=，。\n★\n", "3": ",,z 測試\n"}
    # the page refuses the second line of each (< is not a 大易 root, and must reach the alert as text)
    REFUSED = {"1": "a 一\n1 一", "2": "標點=，。\nxy", "3": "ab 一\n<b>測</b> 試"}

    SCRIPTS = ("candidate_appearance.js", "data_format.js", "config.js")

    RUNNER = r"""
const fs = require("fs"), vm = require("vm");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const source = path => {
    const text = fs.readFileSync(path, "utf8");
    return text.charCodeAt(0) === 0xFEFF ? text.slice(1) : text;
};
process.stdout.write(JSON.stringify(input.runs.map(run => {
    const log = { posts: [], alerts: [], tabs: [], selections: [] };
    const elements = {};
    const element = sel => elements[sel] || (elements[sel] = {
        value: run.values[sel] || "",
        focus() {},
        setSelectionRange(start, end) { log.selections.push([sel, start, end]); },
    });
    const $ = sel => {
        if (typeof sel === "function") return;                  // $(ready): no page is built here
        if (sel === "<div>") {                                  // checkDataFormat()'s escapeHtml()
            let text = "";
            return { text(t) { text = t; return this; },
                     html() { return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); } };
        }
        const link = /^#sidebar a\[href="#(\w+)"\]$/.exec(sel);
        if (link) return input.sidebar.includes(link[1]) ? [{ pane: link[1] }] : [];
        const el = element(sel);
        return {
            0: el, length: 1,
            val(value) { if (value === undefined) return el.value; el.value = value; return this; },
            closest(query) {
                const pane = query === ".tab-pane" && input.panes[sel];
                return pane ? { length: 1, attr: () => pane } : { length: 0 };
            },
        };
    };
    $.get = () => ({ fail() {} });                              // loadConfig() when the script loads
    $.ajax = request => log.posts.push(JSON.parse(request.data));
    $.jAlert = options => log.alerts.push(options);
    const sandbox = {
        $, jQuery: $, imeFolderName: input.ime, includeScriptFile() {},
        navigator: { userAgent: "", appVersion: "" },
        document: { getElementsByTagName: () => [{ innerText: "" }] },
        bootstrap: { Tab: { getOrCreateInstance: link => ({ show() { log.tabs.push(link.pane); } }) } },
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    for (const script of input.scripts) {
        vm.runInContext(source(script), sandbox, { filename: script });
    }
    vm.runInContext("checjConfig = {};" + run.changed.map(key => key + "Changed = true;").join(""), sandbox);
    vm.runInContext("saveConfig();", sandbox);
    if (log.alerts.length && log.alerts[0].onClose) {
        log.alerts[0].onClose();
    }
    return { posts: log.posts, alerts: log.alerts.map(alert => alert.content), tabs: log.tabs,
             selections: log.selections };
})));
"""

    @classmethod
    def setUpClass(cls):
        config_htm = os.path.join(CINBASE_CONFIG_DIR, "config.htm")
        # the ready handler loads each config.htm fragment into the shell's .tab-pane of
        # the same id, and the sidebar link to that id shows it
        parents = parse_page(config_htm).parents
        cls.panes = {name: [parent for parent in parents[name] if parent.endswith("_page")][-1]
                     for name, _, _, _ in cls.TEXT_TABS}
        with open(config_htm, encoding="utf-8-sig") as f:
            page = f.read()
        sidebar = page[page.index('<nav id="sidebar">'):page.index("</nav>")]
        cls.sidebar = re.findall(r'href="#(\w+)"', sidebar)

    def save(self, runs):
        """[(values {textarea id: text}, [changed keys])] -> what each saveConfig() did"""
        request = {
            "scripts": [os.path.join(CINBASE_CONFIG_DIR, "js", name) for name in self.SCRIPTS],
            "ime": "chedayi",
            "panes": {"#" + name: pane for name, pane in self.panes.items()},
            "sidebar": self.sidebar,
            "runs": [{"values": {"#" + name: text for name, text in values.items()}, "changed": changed}
                     for values, changed in runs],
        }
        result = subprocess.run([NODE, "-e", self.RUNNER], input=json.dumps(request),
                                capture_output=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def refused_everywhere(self):
        return {name: self.REFUSED[type_] for name, _, type_, _ in self.TEXT_TABS}

    def test_the_text_tabs_are_the_ones_the_server_saves_and_the_page_shows(self):
        with open(os.path.join(PYTHON_DIR, "cinbase", "configtool.py"), encoding="utf-8-sig") as f:
            posted = set(re.findall(r'data\.get\("(\w+)", None\)', f.read()))
        shells = sorted(glob.glob(os.path.join(PYTHON_DIR, "input_methods", "*", "config", "config.html")))
        for name, key, _, _ in self.TEXT_TABS:
            with self.subTest(textarea=name):
                self.assertIn(key, posted)
                self.assertIn(self.panes[name], self.sidebar)
                for shell in shells:
                    with open(shell, encoding="utf-8-sig") as f:
                        self.assertRegex(f.read(), r'<div id="%s" class="tab-pane\b' % self.panes[name])

    def test_unchanged_text_tabs_are_neither_checked_nor_posted(self):
        result, = self.save([(self.refused_everywhere(), [])])
        self.assertEqual(result["alerts"], [])
        self.assertEqual([sorted(post) for post in result["posts"]], [["config"]])
        self.assertIs(result["posts"][0]["config"].get("candidateMaxWidthMigrated"), True)

    def test_each_changed_text_tab_is_checked_and_posted(self):
        runs = []
        for name, key, type_, _ in self.TEXT_TABS:
            # only this tab changed; every other one holds a refused line
            runs.append((dict(self.refused_everywhere(), **{name: self.VALID[type_]}), [key]))
            runs.append((self.refused_everywhere(), [key]))
        results = self.save(runs)
        for i, (name, key, type_, desc) in enumerate(self.TEXT_TABS):
            saved, refused = results[2 * i], results[2 * i + 1]
            with self.subTest(textarea=name):
                self.assertEqual(saved["alerts"], [])
                self.assertEqual([sorted(post) for post in saved["posts"]], [sorted(["config", key])])
                self.assertEqual(saved["posts"][0][key], self.VALID[type_])

                self.assertEqual(refused["posts"], [])
                self.assertEqual(len(refused["alerts"]), 1)
                self.assertTrue(refused["alerts"][0].startswith(desc + "設定第 2 行「"), refused["alerts"][0])
                self.assertEqual(refused["tabs"], [self.panes[name]])
                first, second = self.REFUSED[type_].split("\n")
                start = len(first) + 1  # BMP text: UTF-16 offsets are len()
                self.assertEqual(refused["selections"], [["#" + name, start, start + len(second)]] * 2)

    def test_the_refused_line_reaches_the_alert_as_text(self):
        result, = self.save([({"extendtable": self.REFUSED["3"]}, ["extendtable"])])
        self.assertIn("「&lt;b&gt;測&lt;/b&gt; 試」", result["alerts"][0])
        self.assertNotIn("<b>", result["alerts"][0])


if __name__ == "__main__":
    unittest.main()
