import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
PYTHON_DIR = os.path.join(ROOT, "python")
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

from cinbase import compositionbuffer as cb


class FakeTS:
    def __init__(self, text="", cursor=0, chars=None):
        self.compositionBufferString = text
        self.compositionBufferCursor = cursor
        self.compositionBufferChar = dict(chars or {})
        self.sent = []

    def setCompositionString(self, s):
        self.sent.append(("string", s))

    def setCompositionCursor(self, c):
        self.sent.append(("cursor", c))


class InsertStringTests(unittest.TestCase):
    def test_insert_at_end(self):
        ts = FakeTS("明天", 2)
        cb.insertString(ts, "好", 0)
        self.assertEqual(ts.compositionBufferString, "明天好")
        self.assertEqual(ts.compositionBufferCursor, 3)
        self.assertIn(("string", "明天好"), ts.sent)
        self.assertIn(("cursor", 3), ts.sent)

    def test_insert_in_middle(self):
        ts = FakeTS("明天", 1)
        cb.insertString(ts, "日", 0)
        self.assertEqual(ts.compositionBufferString, "明日天")
        self.assertEqual(ts.compositionBufferCursor, 2)

    def test_replace_before_cursor(self):
        # removeStringLength 取代游標前的字（組字字根換成輸出字）
        ts = FakeTS("av7", 3)
        cb.insertString(ts, "明", 3)
        self.assertEqual(ts.compositionBufferString, "明")
        self.assertEqual(ts.compositionBufferCursor, 1)

    def test_replace_in_middle(self):
        ts = FakeTS("我av7天", 4)
        cb.insertString(ts, "明", 3)
        self.assertEqual(ts.compositionBufferString, "我明天")
        self.assertEqual(ts.compositionBufferCursor, 2)


class RemoveStringTests(unittest.TestCase):
    def test_backspace_at_end(self):
        ts = FakeTS("明天", 2)
        cb.removeString(ts, 1, True)
        self.assertEqual(ts.compositionBufferString, "明")
        self.assertEqual(ts.compositionBufferCursor, 1)

    def test_backspace_in_middle(self):
        ts = FakeTS("明日天", 2)
        cb.removeString(ts, 1, True)
        self.assertEqual(ts.compositionBufferString, "明天")
        self.assertEqual(ts.compositionBufferCursor, 1)

    def test_delete_in_middle(self):
        ts = FakeTS("明日天", 1)
        cb.removeString(ts, 1, False)
        self.assertEqual(ts.compositionBufferString, "明天")
        self.assertEqual(ts.compositionBufferCursor, 1)

    def test_delete_last_char(self):
        ts = FakeTS("明天", 1)
        cb.removeString(ts, 1, False)
        self.assertEqual(ts.compositionBufferString, "明")
        self.assertEqual(ts.compositionBufferCursor, 1)


class RecordCharTests(unittest.TestCase):
    def test_record_at_end(self):
        ts = FakeTS()
        cb.recordChar(ts, "default", "av7", 1)
        self.assertEqual(ts.compositionBufferChar, {0: ["default", "av7"]})

    def test_insert_shifts_following_records_right(self):
        ts = FakeTS(chars={0: ["default", "a"], 1: ["default", "b"]})
        # 在位置 1 插入：原本 0 不動、1 右移成 2
        cb.recordChar(ts, "default", "x", 1)
        self.assertEqual(ts.compositionBufferChar, {
            0: ["default", "x"],
            1: ["default", "a"],
            2: ["default", "b"],
        })


class DropCharAtTests(unittest.TestCase):
    def test_drop_and_left_shift(self):
        ts = FakeTS(chars={0: ["t", "a"], 1: ["t", "b"], 2: ["t", "c"]})
        cb.dropCharAt(ts, 1)
        self.assertEqual(ts.compositionBufferChar, {0: ["t", "a"], 1: ["t", "c"]})

    def test_drop_without_record_still_shifts(self):
        ts = FakeTS(chars={3: ["t", "x"]})
        cb.dropCharAt(ts, 1)
        self.assertEqual(ts.compositionBufferChar, {2: ["t", "x"]})

    def test_far_record_shifts_exactly_one(self):
        # 迴歸測試：舊寫法邊迭代邊改 key，新 key 會被排到迭代尾端
        # 重複處理，造成 5 一路滑到 1；正確行為是只左移一格
        ts = FakeTS(chars={5: ["t", "x"]})
        cb.dropCharAt(ts, 0)
        self.assertEqual(ts.compositionBufferChar, {4: ["t", "x"]})

    def test_multiple_records_keep_relative_order(self):
        ts = FakeTS(chars={2: ["t", "a"], 4: ["t", "b"], 6: ["t", "c"]})
        cb.dropCharAt(ts, 2)
        self.assertEqual(ts.compositionBufferChar, {3: ["t", "b"], 5: ["t", "c"]})


if __name__ == "__main__":
    unittest.main()
