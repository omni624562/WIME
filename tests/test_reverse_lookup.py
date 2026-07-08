"""RCin/HCin 反向索引（優化項目 19）與舊版全表掃描的等價性測試。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "python"))

from cinbase.rcin import RCin
from cinbase.hcin import HCin


CHARDEFS = {
    "zb": ["虫", "蟲"],
    "ab": ["日", "蟲"],
    "cd": ["虫", "虫"],  # 同鍵重複出現
    "ee": ["月"],
}
KEYNAMES = {c: c.upper() for c in "abcdez"}


def make(cls):
    obj = cls.__new__(cls)
    obj.keynames = dict(KEYNAMES)
    obj.chardefs = {k: list(v) for k, v in CHARDEFS.items()}
    obj._build_reverse_index()
    return obj


def legacy_isHaveKey(chardefs, val):
    return True if [k for k, v in chardefs.items() if val in v] else False


def legacy_getKey(chardefs, val):
    return [k for k, v in chardefs.items() if val in v][0]


def legacy_getKeyList(chardefs, val):
    return [k for k, v in sorted(chardefs.items()) if val in v]


def legacy_getCharEncode(chardefs, keynames, root):
    nunbers = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩']
    i = 0
    result = root + ':'
    for chardef in chardefs:
        for char in chardefs[chardef]:
            if char == root:
                result += '　' + nunbers[i]
                if i < 9:
                    i = i + 1
                for s in chardef:
                    result += keynames[s]
    if result == root + ':':
        result = ''
    return result


class ReverseLookupEquivalenceTests(unittest.TestCase):
    ROOTS = ["虫", "蟲", "日", "月", "貓"]  # 含重複、多鍵、單鍵、不存在

    def test_rcin_matches_legacy(self):
        rc = make(RCin)
        for root in self.ROOTS:
            with self.subTest(root=root):
                self.assertEqual(rc.isHaveKey(root), legacy_isHaveKey(CHARDEFS, root))
                if rc.isHaveKey(root):
                    self.assertEqual(rc.getKey(root), legacy_getKey(CHARDEFS, root))
                self.assertEqual(
                    rc.getCharEncode(root),
                    legacy_getCharEncode(CHARDEFS, KEYNAMES, root))

    def test_hcin_matches_legacy(self):
        hc = make(HCin)
        for root in self.ROOTS:
            with self.subTest(root=root):
                self.assertEqual(hc.isHaveKey(root), legacy_isHaveKey(CHARDEFS, root))
                if hc.isHaveKey(root):
                    self.assertEqual(hc.getKey(root), legacy_getKey(CHARDEFS, root))
                self.assertEqual(hc.getKeyList(root), legacy_getKeyList(CHARDEFS, root))
                self.assertEqual(
                    hc.getCharEncode(root),
                    legacy_getCharEncode(CHARDEFS, KEYNAMES, root))


if __name__ == "__main__":
    unittest.main()
