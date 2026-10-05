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
- The old default candidateMaxWidth (300) is stored in most users' config.json
  and is migrated to the new default (340: 6 candidates at 16pt need 336px) on load,
  but only in files without candidateMaxWidthMigrated (the settings page writes it):
  the migration used to run on every load, so 300 could never be chosen.
- candPerRow has done nothing since the classic candidate window was removed; it
  is dropped from old config files.
- The blank lines the settings page left in symbols.dat are removed.
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
            "candidateMinWidth": None,    # an emptied number field on the settings page
            "candPerPage": 9.0,           # hand edit: float
            "keyboardLayout": 2 ** 40,    # ctypes OverflowError before
            "selKeyType": 6,              # IndexError in getSelKeys() before
            "candidatePerRow": -1,
            "fontSize": "",
            "candidateOpacity": 5,
        })
        self.assertEqual(cfg.candidateMinWidth, 286)
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

    def test_old_default_candidate_max_width_is_migrated(self):
        self.assertEqual(cc.ChewingConfig(load=False).candidateMaxWidth, 340)
        # the first load and the settings page write every value, so most users have 300 stored
        for stored, expected in ((300, 340), ("300", 340), (320, 320), (360, 360), (280, 280)):
            with self.subTest(stored=stored):
                self.assertEqual(self.load({"candidateMaxWidth": stored}).candidateMaxWidth, expected)
        # the settings tool shows the same value (it normalizes the file with normalizeValues)
        values = cc.normalizeValues({"candidateMaxWidth": 300}, cc.defaultValues())
        self.assertEqual(values, {"candidateMaxWidth": 340})

    def test_chosen_300_is_kept_after_the_migration(self):
        for marker in (True, "true", 1):
            with self.subTest(marker=marker):
                cfg = self.load({"candidateMaxWidth": 300, "candidateMaxWidthMigrated": marker})
                self.assertEqual(cfg.candidateMaxWidth, 300)
        self.assertEqual(self.load({"candidateMaxWidth": 300, "candidateMaxWidthMigrated": False})
                         .candidateMaxWidth, 340)
        # the settings tool shows the defaults overlaid with the file, through normalizeValues
        defaults = cc.defaultValues()
        self.assertIs(defaults["candidateMaxWidthMigrated"], False)
        old = cc.normalizeValues(dict(defaults, candidateMaxWidth=300), defaults)
        self.assertEqual(old["candidateMaxWidth"], 340)
        chosen = cc.normalizeValues(dict(defaults, candidateMaxWidth=300, candidateMaxWidthMigrated=True), defaults)
        self.assertEqual(chosen["candidateMaxWidth"], 300)

    def test_migration_marker_comes_from_the_user_file(self):
        # the shared config object is reloaded: the marker of the file read before must
        # not keep an old file's 300
        cfg = self.load({"candidateMaxWidth": 300, "candidateMaxWidthMigrated": True})
        self.assertEqual(cfg.candidateMaxWidth, 300)
        self.write({"candidateMaxWidth": 300})
        stamp = time.time() + 5
        os.utime(self.path, (stamp, stamp))
        cfg._lastUpdateTime = None
        cfg.update()
        self.assertEqual(cfg.candidateMaxWidth, 340)

    def test_normalize_values_keeps_unknown_keys(self):
        defaults = cc.defaultValues()
        values = cc.normalizeValues({"candidateMinWidth": None, "test_input_text": None}, defaults)
        self.assertEqual(values, {"candidateMinWidth": 286, "test_input_text": None})

    def test_retired_settings_are_dropped(self):
        # candPerRow (the classic window's per-row count) does nothing since that window
        # was removed; the per-row count is candidatePerRow
        cfg = self.load({"candPerRow": 5, "candPerPage": 4})
        self.assertFalse(hasattr(cfg, "candPerRow"))
        self.assertNotIn("candPerRow", cfg.toJson())
        self.assertEqual(cfg.candPerPage, 4)
        # the settings tool reads config.json itself: it must not get it back either,
        # or saving the settings page writes it out again
        values = cc.normalizeValues({"candPerRow": 5, "candPerPage": 4}, cc.defaultValues())
        self.assertEqual(values, {"candPerPage": 4})

    def test_new_config_file_has_no_retired_settings(self):
        cc.ChewingConfig()
        self.assertNotIn("candPerRow", json.loads(self.read().decode("utf-8")))


class BlankSymbolLineTests(ConfigFileTestCase):
    """symbols.dat: libchewing reads each blank line as an empty ` menu item, and
    the settings page used to add one each time the 特殊符號 were edited."""

    def setUp(self):
        super().setUp()
        self.symbols = os.path.join(self.dir, "symbols.dat")
        self.addCleanup(lambda: os.path.exists(self.symbols) and os.remove(self.symbols))

    def write_symbols(self, data):
        with open(self.symbols, "wb") as f:
            f.write(data)
        stamp = time.time() - 60
        os.utime(self.symbols, (stamp, stamp))
        return os.stat(self.symbols).st_mtime_ns

    def read_symbols(self):
        with open(self.symbols, "rb") as f:
            return f.read()

    def test_blank_lines_are_removed_when_the_settings_load(self):
        # line endings, a line of spaces and a last line without a newline stay as they are
        self.write_symbols("甲=１\r\n\r\n乙=２\n\n \r\n丙=３\r\n\r\n\r\n丁".encode("utf-8"))
        cc.ChewingConfig()
        self.assertEqual(self.read_symbols(), "甲=１\r\n乙=２\n \r\n丙=３\r\n丁".encode("utf-8"))
        self.assertEqual([name for name in os.listdir(self.dir) if name.endswith(".tmp")], [])

    def test_a_file_without_blank_lines_is_not_rewritten(self):
        mtime = self.write_symbols("甲=１\r\n乙=２\r\n".encode("utf-8"))
        cc.ChewingConfig()
        self.assertEqual(os.stat(self.symbols).st_mtime_ns, mtime)

    def test_a_changed_file_is_cleaned_before_the_reload(self):
        cfg = cc.ChewingConfig()
        version = cfg.getVersion()
        self.write_symbols("甲=１\r\n\r\n".encode("utf-8"))
        cfg._lastUpdateTime = None
        cfg.update()
        self.assertEqual(self.read_symbols(), "甲=１\r\n".encode("utf-8"))
        # the version taken is the cleaned file's: it does not change again later
        self.assertTrue(cfg.isFullReloadNeeded(version))
        self.assertEqual(cfg.getVersion()[1], os.path.getmtime(self.symbols))


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
