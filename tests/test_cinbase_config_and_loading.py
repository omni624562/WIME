"""Regression tests for CinBase settings and table loading.

- The shipped per-IME defaults (python/input_methods/<ime>/config/config.json)
  are UTF-8 with Chinese text; they were read in the ANSI code page and the
  error swallowed, so on zh-TW Windows none of them ever applied.
- A user config.json that failed to load was overwritten with defaults.
- Values of the wrong type (the settings page saves an emptied number field
  as "") raised on IME creation or on every keystroke.
- A code table that failed to load was never loaded again by that instance,
  and while it was missing every key - Ctrl+C, Enter, arrows - was swallowed.
- Missing reverse-lookup / homophone tables started a thread on every request.
"""

import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import cinbase_harness as h
from cinbase.config import CinBaseConfig


def setUpModule():
    global _appdata, _real_play
    _appdata = h.IsolatedAppData()
    _real_play = h.cinbase.winsound.PlaySound
    h.cinbase.winsound.PlaySound = lambda *a, **k: None


def tearDownModule():
    h.cinbase.winsound.PlaySound = _real_play
    _appdata.close()


def fresh_config(ime):
    cfg = type(CinBaseConfig)()
    cfg.imeDirName = ime
    cfg.load()
    return cfg


class ConfigLoadingTests(unittest.TestCase):
    def tearDown(self):
        ime_dir = _appdata.ime_dir("chedayi")
        for name in os.listdir(ime_dir):
            os.remove(os.path.join(ime_dir, name))

    def test_shipped_defaults_are_applied(self):
        cfg = fresh_config("chedayi")
        self.assertEqual(cfg.imeDisplayName, "大易")
        self.assertTrue(cfg.directShowCand)
        self.assertEqual(cfg.selWildcardType, 1)
        self.assertTrue(cfg.candidateModernStyle)

        cfg = fresh_config("checj")
        self.assertEqual(cfg.imeDisplayName, "酷倉")
        self.assertTrue(cfg.directShowCand)

    def test_user_config_with_chinese_text_is_loaded(self):
        h.write_user_config("chedayi", {"imeDisplayName": "我的大易", "candPerPage": 5})
        cfg = fresh_config("chedayi")
        self.assertEqual(cfg.imeDisplayName, "我的大易")
        self.assertEqual(cfg.candPerPage, 5)

    def test_user_config_with_bom_is_loaded(self):
        path = os.path.join(_appdata.ime_dir("chedayi"), "config.json")
        with open(path, "w", encoding="utf-8-sig") as f:
            json.dump({"candPerPage": 4}, f)
        self.assertEqual(fresh_config("chedayi").candPerPage, 4)

    def test_broken_user_config_is_not_overwritten(self):
        broken = '{"candPerPage": 5, "imeDisplayName": "我的'   # truncated
        path = h.write_user_config("chedayi", broken)
        cfg = fresh_config("chedayi")
        self.assertEqual(cfg.imeDisplayName, "大易")          # falls back to the defaults
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), broken)                # ... but keeps the user's file
        backups = [n for n in os.listdir(os.path.dirname(path)) if n.startswith("config.json.broken-")]
        self.assertEqual(len(backups), 1)

    def test_values_of_the_wrong_type_are_normalized(self):
        h.write_user_config("chedayi", {
            "candidatePerRow": "", "candPerPage": "7", "fontSize": 0, "candPerRow": None,
            "directShowCand": "false", "selWildcardType": 2, "selCinType": -1,
            "imeDisplayName": 123, "candidateStyle": "big",
        })
        cfg = fresh_config("chedayi")
        self.assertEqual(cfg.candidatePerRow, 6)
        self.assertEqual(cfg.candPerPage, 7)
        self.assertEqual(cfg.fontSize, 12)
        self.assertEqual(cfg.candPerRow, 10)       # chedayi's shipped default
        self.assertIs(cfg.directShowCand, False)
        self.assertEqual(cfg.selWildcardType, 1)   # out of range -> shipped default
        self.assertEqual(cfg.selCinType, 0)
        self.assertEqual(cfg.imeDisplayName, "123")
        self.assertIsInstance(cfg.candidateStyle, dict)

    def test_save_leaves_a_complete_file(self):
        cfg = fresh_config("chedayi")
        cfg.candPerPage = 8
        cfg.save()
        ime_dir = _appdata.ime_dir("chedayi")
        with open(os.path.join(ime_dir, "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["candPerPage"], 8)
        self.assertNotIn("config.json.tmp", os.listdir(ime_dir))


@h.requires_tables
class ConfigValuesInTheImeTests(unittest.TestCase):
    def test_blank_number_fields_do_not_break_the_ime(self):
        service = h.make_service("chedayi", user_config={
            "candidatePerRow": "", "candPerRow": "", "candPerPage": "", "candMaxItems": ""})
        commits, _ = h.type_keys(service, ["x", "SPACE"])
        self.assertEqual(len(commits), 1)

    def test_unknown_wildcard_type(self):
        service = h.make_service("checj", user_config={"selWildcardType": 7, "supportWildcard": True})
        self.assertIn(service.selWildcardChar, ("z", "*"))
        h.type_keys(service, ["h", "z", "SPACE"])

    def test_table_index_out_of_range(self):
        for value in (99, "abc", -3):
            with self.subTest(selCinType=value):
                service = h.make_service("chedayi", user_config={"selCinType": value})
                commits, _ = h.type_keys(service, ["x", "SPACE"])
                self.assertEqual(len(commits), 1)

    def test_user_data_file_in_ansi_encoding(self):
        # a symbols.dat hand-edited in the legacy code page used to abort
        # initCinBaseContext and leave the other tables missing
        ime_dir = _appdata.ime_dir("chedayi")
        path = os.path.join(ime_dir, "symbols.dat")
        # the ANSI code page of this machine: cp950 on zh-TW, cp1252 on CI
        category = "我的符號"
        try:
            category.encode("mbcs", "strict")
        except UnicodeEncodeError:
            category = "Café"
        with open(path, "w", encoding="mbcs") as f:
            f.write(category + "=★☆\r\n" if category == "我的符號" else category + "=^_^\r\n")
        with open(path, "rb") as f:
            self.assertRaises(UnicodeDecodeError, f.read().decode, "utf-8")
        try:
            service = h.make_service("chedayi")
            self.assertIn(category, service.symbols.getKeyNames())
            for name in ("swkb", "fsymbols", "flangs", "userphrase", "msymbols", "extendtable", "dsymbols"):
                self.assertTrue(hasattr(service, name), name)
        finally:
            os.remove(path)

    def test_unreadable_user_data_file_falls_back_to_the_shipped_one(self):
        ime_dir = _appdata.ime_dir("chedayi")
        path = os.path.join(ime_dir, "msymbols.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{broken")
        try:
            service = h.make_service("chedayi")
            self.assertTrue(service.msymbols.chardefs)
        finally:
            os.remove(path)


class _TableTestBase(unittest.TestCase):
    IME = "chedayi"

    def setUp(self):
        h._ime_class(self.IME)
        self.module = h._modules[self.IME]
        self.table = self.module.CinTable
        self.empty_dir = tempfile.mkdtemp()
        self.starts = []
        # run background loads synchronously so the tests can see their result
        loader = h.cinbase.LoadCinTable

        def start(thread):
            self.starts.append(thread)
            loader.run(thread)
        patcher = mock.patch.object(loader, "start", start)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.empty_dir, ignore_errors=True)
        # leave a clean slate: the next service loads its table synchronously again
        for table in (self.module.CinTable, self.module.RCinTable, self.module.HCinTable):
            table.lastLoadFailure = 0.0
        self.table.cin = None
        self.table.curCinType = None

    def expire_retry_interval(self, table=None):
        (table or self.table).lastLoadFailure -= h.cinbase.TABLE_RETRY_INTERVAL + 1


@h.requires_tables
class MissingTableTests(_TableTestBase):
    def make_service_without_tables(self):
        self.table.cin = None
        self.table.curCinType = None
        with mock.patch.object(type(CinBaseConfig), "getJsonDir", return_value=self.empty_dir):
            return h.make_service(self.IME)

    def test_other_keys_still_reach_the_application(self):
        service = self.make_service_without_tables()
        self.assertIsNone(service.cin)
        for key, kwargs in (("c", {"ctrl": True}), ("ENTER", {}), ("LEFT", {}), ("BACK", {})):
            with self.subTest(key=key):
                reply = h._send(service, "filterKeyDown", h.key_event(key, **kwargs), key)
                self.assertFalse(reply.get("return"))
        reply = h._send(service, "filterKeyDown", h.key_event("x"), "x")
        self.assertTrue(reply.get("return"))   # composing keys are held while the table is missing

    def test_table_is_loaded_once_the_file_is_back(self):
        service = self.make_service_without_tables()
        service.checkConfigChange()
        self.assertEqual(self.starts, [], "retried right after the failure")

        selCinFile = service.cinFileList[service.cfg.selCinType]
        shutil.copy(os.path.join(h.JSON_DIR, selCinFile), self.empty_dir)
        self.expire_retry_interval()
        service.checkConfigChange()
        self.assertEqual(len(self.starts), 1)
        self.assertIsNotNone(service.cin)
        commits, _ = h.type_keys(service, ["x", "SPACE"])
        self.assertEqual(len(commits), 1)

    def test_failed_reload_keeps_the_current_table(self):
        service = h.make_service(self.IME)
        current = service.cin
        service.jsondir = self.empty_dir
        service.cfg.selCinType = 1      # switch to a table that is not there
        service.checkConfigChange()
        self.assertEqual(len(self.starts), 1)
        self.assertIs(service.cin, current)
        commits, _ = h.type_keys(service, ["x", "SPACE"])
        self.assertEqual(len(commits), 1)
        for _ in range(5):
            service.checkConfigChange()
        self.assertEqual(len(self.starts), 1, "retried on every request")

    def test_deactivate_without_a_table(self):
        service = self.make_service_without_tables()
        h.request(service, "onDeactivate")


@h.requires_tables
class LookupTableTests(_TableTestBase):
    def count_starts(self, loader):
        starts = []

        def start(thread):
            starts.append(thread)
            loader.run(thread)
        patcher = mock.patch.object(loader, "start", start)
        patcher.start()
        self.addCleanup(patcher.stop)
        return starts

    def test_missing_homophone_table_is_not_reloaded_on_every_request(self):
        starts = self.count_starts(h.cinbase.LoadHCinTable)
        service = h.make_service(self.IME, homophoneQuery=True)
        service.jsondir = self.empty_dir
        self.module.HCinTable.cin = None
        self.module.HCinTable.curCinType = None
        for _ in range(5):
            service.checkConfigChange()
        self.assertEqual(len(starts), 1)
        self.assertIsNone(self.module.HCinTable.cin)

        messages = []
        show = service.showMessage
        service.showMessage = lambda message, duration=3: (messages.append(message), show(message, duration))
        _, reply = h.type_keys(service, ["x"])
        self.assertTrue(reply.get("candidateList"))
        h.press(service, "`")    # homophone lookup of the highlighted candidate
        self.assertIn("同音字碼表檔案不存在！", messages)

    def test_missing_reverse_lookup_table_is_not_reloaded_on_every_request(self):
        starts = self.count_starts(h.cinbase.LoadRCinTable)
        service = h.make_service(self.IME, imeReverseLookup=True)
        service.jsondir = self.empty_dir
        self.module.RCinTable.cin = None
        self.module.RCinTable.curCinType = None
        for _ in range(5):
            service.checkConfigChange()
        self.assertEqual(len(starts), 1)
        self.assertTrue(service.RCinFileNotExist)

    def test_lookup_table_index_out_of_range(self):
        self.count_starts(h.cinbase.LoadHCinTable)
        service = h.make_service(self.IME, homophoneQuery=True)
        self.module.HCinTable.cin = None
        self.module.HCinTable.curCinType = None
        service.cfg.selHCinType = 50
        service.checkConfigChange()
        self.assertIsNotNone(self.module.HCinTable.cin)
        self.assertEqual(self.module.HCinTable.curCinType, 0)


class CountFileTests(unittest.TestCase):
    def test_corrupt_count_file_is_kept_aside(self):
        ime_dir = _appdata.ime_dir("chedayi")
        path = os.path.join(ime_dir, "cincount.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"x": {"大": {"count": 3')
        try:
            table = h.cinbase.Cin(io.StringIO('{"chardefs": {}, "keynames": {}}'), "chedayi", False)
            table.cincount["x"] = {"大": {"count": 1, "last": 1.0}}
            table._count_dirty = True
            table.__del__()
            backups = [n for n in os.listdir(ime_dir) if n.startswith("cincount.json.broken-")]
            self.assertEqual(len(backups), 1)
        finally:
            for name in os.listdir(ime_dir):
                if name.startswith("cincount"):
                    os.remove(os.path.join(ime_dir, name))

    def test_second_close_does_not_write_an_empty_file(self):
        ime_dir = _appdata.ime_dir("chedayi")
        path = os.path.join(ime_dir, "cincount.json")
        table = h.cinbase.Cin(io.StringIO('{"chardefs": {}, "keynames": {}}'), "chedayi", False)
        table.cincount["x"] = {"大": {"count": 1, "last": 1.0}}
        table._count_dirty = True
        with mock.patch("cinbase.cin.os.replace", side_effect=PermissionError("locked")):
            table.__del__()                # the first save fails
        table.__del__()                    # the second call used to save the emptied {}
        try:
            self.assertFalse(os.path.exists(path) and os.path.getsize(path) <= 2)
        finally:
            for name in os.listdir(ime_dir):
                if name.startswith("cincount"):
                    os.remove(os.path.join(ime_dir, name))

    @h.requires_tables
    def test_table_statistics_are_not_saved_as_counts(self):
        with open(os.path.join(h.JSON_DIR, "dayi4.json"), encoding="utf-8") as f:
            table = h.cinbase.Cin(f, "chedayi", False)
        self.assertNotIn("big5F", table.cincount)
        table.__del__()


class UserPhraseParserTests(unittest.TestCase):
    def test_blank_lines_bom_and_trailing_commas(self):
        phrases = h.cinbase.userphrase(["﻿我=們,的,\r\n", "\r\n", "=孤兒\r\n", "你=們\r\n", "我=們們\r\n"])
        self.assertEqual(phrases.getKeyNames(), ["我", "你"])
        self.assertEqual(phrases.getCharDef("我"), ["們", "的", "們們"])
        self.assertEqual(phrases.getCharDef("沒有"), [])


if __name__ == "__main__":
    unittest.main()
