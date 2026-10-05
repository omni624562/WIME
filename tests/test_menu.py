import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
PYTHON_DIR = os.path.join(ROOT, "python")
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

from cinbase import menu


class FakeTS:
    pass


class MainMenuTests(unittest.TestCase):
    def test_labels_match_ids(self):
        labels = menu.mainMenuLabels()
        self.assertEqual(len(labels), 6)
        for label in labels:
            self.assertIsNotNone(menu.mainMenuId(label))

    def test_frequent_items_come_first(self):
        labels = menu.mainMenuLabels()
        # 常用的輸出類在前、設定類在後
        self.assertEqual(menu.mainMenuId(labels[0]), "symbols")
        self.assertEqual(menu.mainMenuId(labels[1]), "emoji")
        self.assertEqual(menu.mainMenuId(labels[-1]), "settings")

    def test_unknown_label_returns_none(self):
        self.assertIsNone(menu.mainMenuId("不存在"))
        self.assertIsNone(menu.mainMenuId(menu.BACK_ITEM))


class ToggleMenuTests(unittest.TestCase):
    def make_ts(self, ime, **state):
        ts = FakeTS()
        ts.imeDirName = ime
        for attr in menu.toggleAttrsFor(ime):
            setattr(ts, attr, False)
        for key, value in state.items():
            setattr(ts, key, value)
        return ts

    def test_labels_reflect_state(self):
        ts = self.make_ts("chedayi", intelligentSelect=True)
        labels, attrs = menu.buildToggleItems(ts)
        self.assertEqual(len(labels), len(attrs))
        i = attrs.index("intelligentSelect")
        self.assertTrue(labels[i].startswith("☑"))
        j = attrs.index("supportWildcard")
        self.assertTrue(labels[j].startswith("☐"))

    def test_per_ime_lists(self):
        # autoClearCompositionChar 已隨「查無組字保留碼」行為移除
        self.assertEqual(len(menu.toggleAttrsFor("chedayi")), 11)
        self.assertEqual(len(menu.toggleAttrsFor("chephonetic")), 7)
        self.assertEqual(len(menu.toggleAttrsFor("cheez")), 5)
        self.assertEqual(len(menu.toggleAttrsFor("checj")), 8)

    def test_homophone_toggle_hidden_when_backtick_is_a_root(self):
        class FakeCin:
            def __init__(self, keys):
                self.keys = keys

            def isInKeyName(self, key):
                return key in self.keys

        ts = self.make_ts("chedayi")
        ts.cin = FakeCin("abc")
        self.assertIn("homophoneQuery", menu.buildToggleItems(ts)[1])
        ts.cin = FakeCin("abc`")   # 大易三碼：` 是字根「巷」
        labels, attrs = menu.buildToggleItems(ts)
        self.assertNotIn("homophoneQuery", attrs)
        self.assertEqual(len(labels), len(attrs))

    def test_smart_select_labels_describe_the_previous_character_design(self):
        # 智慧選字只把「在同一個前一字之後選過的字」提前，不依次數或最近選過重排；
        # 以前的「智慧選字」「近期選字優先」讓人以為常用字會往前排
        labels = dict(menu.TOGGLE_DEFS)
        for attr in ("intelligentSelect", "intelligentSelectRecent", "intelligentSelectContext"):
            with self.subTest(attr=attr):
                self.assertIn("前一字", labels[attr])
        self.assertEqual(len(set(labels.values())), len(labels))   # toggleIndex() matches by text

    def test_toggle_then_rebuild_updates_mark(self):
        ts = self.make_ts("checj")
        labels, attrs = menu.buildToggleItems(ts)
        self.assertTrue(labels[0].startswith("☐"))
        setattr(ts, attrs[0], True)
        labels2, _ = menu.buildToggleItems(ts)
        self.assertTrue(labels2[0].startswith("☑"))


class BackItemTests(unittest.TestCase):
    def test_with_back_prepends(self):
        self.assertEqual(menu.withBack(["a", "b"]), [menu.BACK_ITEM, "a", "b"])

    def test_with_back_copies_input(self):
        original = ["a"]
        result = menu.withBack(original)
        result.append("b")
        self.assertEqual(original, ["a"])


class BreadcrumbTests(unittest.TestCase):
    def test_root_header(self):
        ts = FakeTS()
        menu.resetPath(ts)
        self.assertEqual(menu.headerText(ts), "選單 功能選單")

    def test_nested_path(self):
        ts = FakeTS()
        menu.resetPath(ts)
        menu.pushPath(ts, "特殊符號")
        self.assertEqual(menu.headerText(ts), "選單 特殊符號")
        menu.pushPath(ts, "括號")
        self.assertEqual(menu.headerText(ts), "選單 特殊符號 › 括號")
        menu.popPath(ts)
        self.assertEqual(menu.headerText(ts), "選單 特殊符號")

    def test_pop_empty_is_safe(self):
        ts = FakeTS()
        menu.resetPath(ts)
        menu.popPath(ts)
        self.assertEqual(menu.headerText(ts), "選單 功能選單")

    def test_push_without_init_is_safe(self):
        ts = FakeTS()
        menu.pushPath(ts, "表情符號")
        self.assertEqual(menu.headerText(ts), "選單 表情符號")


if __name__ == "__main__":
    unittest.main()
