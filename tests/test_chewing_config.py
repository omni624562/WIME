"""新酷音 settings (input_methods/chewing/chewing_config.py).

- A config.json the backend cannot parse (UTF-8 BOM, a trailing comma, not an
  object) used to be overwritten with the defaults, losing every setting.
- Values from the settings page or hand edits reach ctypes and list indexing:
  null (an emptied number field), floats, huge or out-of-range numbers, keys that
  shadow methods ("update") or private fields - they broke activation or every key.
- The legacy %USERPROFILE%\\PIME\\chewing migration copied the old folder over
  the current one, replacing the learned phrases in chewing.sqlite3.
- The reload throttle used the wall clock, so reloads stopped after the clock
  was set back.
"""

import importlib
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

import cinbase_harness

_appdata = None
cc = None


def setUpModule():
    global _appdata, cc
    _appdata = cinbase_harness.IsolatedAppData()
    cc = importlib.import_module("input_methods.chewing.chewing_config")


def tearDownModule():
    _appdata.close()


class ConfigFileTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(os.environ["APPDATA"], "PIME", "chewing")
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "config.json")
        self.addCleanup(self.clean)

    def clean(self):
        for name in os.listdir(self.dir):
            if name.startswith("config.json") or name.startswith("legacy-"):
                os.remove(os.path.join(self.dir, name))

    def write(self, data, encoding="utf-8"):
        with open(self.path, "w", encoding=encoding) as f:
            f.write(data if isinstance(data, str) else json.dumps(data))

    def read(self):
        with open(self.path, "rb") as f:
            return f.read()


class BrokenConfigFileTests(ConfigFileTestCase):
    def test_bom_is_accepted(self):
        self.write(json.dumps({"candPerPage": 5, "keyboardLayout": 2}), encoding="utf-8-sig")
        before = self.read()
        cfg = cc.ChewingConfig()
        self.assertEqual((cfg.candPerPage, cfg.keyboardLayout), (5, 2))
        self.assertEqual(self.read(), before)

    def test_unparsable_file_is_kept(self):
        for text in ('{"candPerPage": 5,}', "[1, 2]", "\"text\"", "{not json"):
            with self.subTest(text=text):
                self.clean()
                self.write(text)
                cfg = cc.ChewingConfig()
                self.assertEqual(self.read().decode("utf-8"), text)  # overwritten with defaults before
                self.assertEqual(cfg.candPerPage, 9)
                backups = [name for name in os.listdir(self.dir) if name.startswith("config.json.broken-")]
                self.assertEqual(len(backups), 1)

    def test_runtime_edit_with_a_typo_keeps_the_current_settings(self):
        self.write({"candPerPage": 5})
        cfg = cc.ChewingConfig()
        self.write('{"candPerPage": 7,}')
        stamp = time.time() + 5
        os.utime(self.path, (stamp, stamp))
        cfg._lastUpdateTime = None
        cfg.update()
        self.assertEqual(cfg.candPerPage, 5)
        self.assertEqual(self.read().decode("utf-8"), '{"candPerPage": 7,}')

    def test_missing_file_is_created_with_defaults(self):
        cc.ChewingConfig()
        self.assertEqual(json.loads(self.read().decode("utf-8"))["candPerPage"], 9)


class ValueNormalizationTests(ConfigFileTestCase):
    def load(self, values):
        self.write(values)
        return cc.ChewingConfig()

    def test_bad_numbers_fall_back_to_defaults(self):
        cfg = self.load({
            "candPerRow": None,           # an emptied number field on the settings page
            "candPerPage": 9.0,           # hand edit: float
            "keyboardLayout": 2 ** 40,    # ctypes OverflowError before
            "selKeyType": 6,              # IndexError in getSelKeys() before
            "candidatePerRow": -1,
            "fontSize": "",
            "candidateOpacity": 5,
        })
        self.assertEqual(cfg.candPerRow, 3)
        self.assertEqual(cfg.candPerPage, 9)
        self.assertIsInstance(cfg.candPerPage, int)
        self.assertEqual(cfg.keyboardLayout, 0)
        self.assertEqual(cfg.selKeyType, 0)
        self.assertEqual(cfg.getSelKeys(), "1234567890")
        self.assertEqual(cfg.candidatePerRow, 6)
        self.assertEqual(cfg.fontSize, 16)
        self.assertEqual(cfg.candidateOpacity, 100)

    def test_valid_values_are_kept(self):
        cfg = self.load({"selKeyType": "1", "candPerPage": 5, "keyboardLayout": 12,
                         "addPhraseForward": 0, "shiftMoveCursor": True, "candidateTheme": "Graphite"})
        self.assertEqual(cfg.selKeyType, 1)
        self.assertEqual(cfg.candPerPage, 5)
        self.assertEqual(cfg.keyboardLayout, 12)
        self.assertFalse(cfg.addPhraseForward)   # the settings page stores selects as 0/1
        self.assertTrue(cfg.shiftMoveCursor)     # and this checkbox as a bool
        self.assertEqual(cfg.candidateTheme, "Graphite")

    def test_wrong_types(self):
        cfg = self.load({"autoLearn": "false", "escCleanAllBuf": None, "candidateTheme": 3,
                         "candidateStyle": {"contentMargin": 8, "textMargin": "4", "borderRadius": True},
                         "candidateColors": []})
        self.assertIs(cfg.autoLearn, False)
        self.assertIs(cfg.escCleanAllBuf, True)
        self.assertEqual(cfg.candidateTheme, "System")
        self.assertEqual(cfg.candidateStyle, {"contentMargin": 8})
        self.assertEqual(cfg.candidateColors, {})

    def test_keys_that_shadow_methods_or_private_fields_are_ignored(self):
        cfg = self.load({"update": 1, "getSelKeys": "x", "_lastUpdateTime": 1e12, "_version": [9, 9, 9],
                         "unknownKey": 1, "candPerPage": 4})
        self.assertTrue(callable(cfg.update))
        self.assertEqual(cfg.getSelKeys(), "1234567890")
        self.assertNotEqual(cfg._lastUpdateTime, 1e12)
        self.assertFalse(hasattr(cfg, "unknownKey"))
        self.assertEqual(cfg.candPerPage, 4)

    def test_normalize_values_keeps_unknown_keys(self):
        defaults = cc.defaultValues()
        values = cc.normalizeValues({"candPerRow": None, "test_input_text": None}, defaults)
        self.assertEqual(values, {"candPerRow": 3, "test_input_text": None})


class ReloadThrottleTests(ConfigFileTestCase):
    def test_reload_after_the_wall_clock_was_set_back(self):
        self.write({"candPerPage": 5})
        cfg = cc.ChewingConfig()
        self.write({"candPerPage": 7})
        stamp = time.time() + 5
        os.utime(self.path, (stamp, stamp))
        real_time = time.time
        with mock.patch("time.time", lambda: real_time() - 3600), \
                mock.patch("time.monotonic", lambda: real_time() + 3600):
            cfg.update()
        self.assertEqual(cfg.candPerPage, 7)


class LegacyMigrationTests(ConfigFileTestCase):
    def setUp(self):
        super().setUp()
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        patcher = mock.patch.dict(os.environ, {"USERPROFILE": self.home, "HOME": self.home})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.legacy = os.path.join(self.home, "PIME", "chewing")
        os.makedirs(self.legacy)
        with open(os.path.join(self.legacy, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"candPerPage": 4}, f)
        with open(os.path.join(self.legacy, "chewing.sqlite3"), "wb") as f:
            f.write(b"old phrases")
        self.db = os.path.join(self.dir, "chewing.sqlite3")
        self.addCleanup(lambda: os.path.exists(self.db) and os.remove(self.db))

    def test_current_phrases_are_never_overwritten(self):
        # the user deleted config.json to reset the settings
        with open(self.db, "wb") as f:
            f.write(b"current phrases")
        cfg = cc.ChewingConfig()
        with open(self.db, "rb") as f:
            self.assertEqual(f.read(), b"current phrases")
        self.assertEqual(cfg.candPerPage, 9)

    def test_first_run_migrates_the_old_folder(self):
        cfg = cc.ChewingConfig()
        self.assertEqual(cfg.candPerPage, 4)
        with open(self.db, "rb") as f:
            self.assertEqual(f.read(), b"old phrases")


if __name__ == "__main__":
    unittest.main()
