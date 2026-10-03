"""新酷音 context lifecycle with the real libchewing (see chewing_harness).

- A config change while the keyboard is closed (no context) used to raise on
  the next request.
- chewing_new2() returning NULL (user phrase database locked / corrupt, data
  files missing) was not detected: every key was swallowed without output.
- A native fault inside chewing.dll (the bundled 2021 C libchewing) escaped as
  OSError, so the C++ side reset the pipe, and the same key sequence kept failing.
- Saving symbols.dat / swkb.dat rebuilt the context mid-composition and reset the
  中/英 mode.
- Invalid UTF-8 from libchewing (a symbols.dat line over 511 bytes is cut in the
  middle of a character) made every following key raise.
- A non-ASCII %APPDATA% (e.g. a Chinese user name) made libchewing ignore the
  user's own symbol files, because the path was passed as UTF-8.
"""

import os
import shutil
import sqlite3
import tempfile
import time
import unittest

import cinbase_harness

_appdata = None
ch = None
libchewing = None


def setUpModule():
    global _appdata, ch, libchewing
    _appdata = cinbase_harness.IsolatedAppData()
    import chewing_harness
    ch = chewing_harness
    ch.load_module()
    import libchewing as _libchewing
    libchewing = _libchewing


def tearDownModule():
    ch.close_all()
    _appdata.close()


SHIFT_SPACE_GUID = "{f1dae0fb-8091-44a7-8a0c-3082a1515447}"


def config_dir():
    return ch.config().getConfigDir()


def force_config_check():
    ch.config()._lastUpdateTime = None  # skip the 3 s throttle


class ChewingTestCase(unittest.TestCase):
    def service(self, **overrides):
        override = ch.ConfigOverride(**overrides)
        self.addCleanup(override.restore)
        return ch.make_service()

    def tearDown(self):
        ch.close_all()

    def type(self, service, keys):
        commits, _ = ch.type_keys(service, keys)
        return "".join(commits)


class KeyboardClosedTests(ChewingTestCase):
    def test_config_change_while_the_keyboard_is_closed(self):
        s = self.service()
        ch.request(s, "onKeyboardStatusChanged", opened=False)
        self.assertIsNone(s.chewingContext)
        path = ch.config().getConfigFile()
        ch.config().save()
        stamp = time.time() + 5
        os.utime(path, (stamp, stamp))  # a newer config.json
        force_config_check()
        ch.request(s, "onKillFocus")  # AttributeError on None before
        force_config_check()
        ch.request(s, "onKeyboardStatusChanged", opened=True)
        self.assertIsNotNone(s.chewingContext)
        self.assertEqual(self.type(s, list("su3") + ["ENTER"]), "你")


class ContextCreationTests(ChewingTestCase):
    def test_binding_raises_on_null_context(self):
        with self.assertRaises(libchewing.ChewingError):
            libchewing.ChewingContext(syspath=b"C:\\no\\such\\dir", userpath=b":memory:")

    def test_closed_context_is_safe_to_call(self):
        ctx = libchewing.ChewingContext(syspath=libchewing.encodeDataPath(libchewing.CHEWING_DATA_DIR),
                                        userpath=b":memory:")
        ctx.handle_Default(ord("s"))
        ctx.close()
        ctx.close()
        self.assertLessEqual(ctx.bopomofo_Check(), 0)  # a NULL context (error), not the freed pointer

    def test_locked_user_phrase_database_falls_back_to_memory(self):
        module = ch.load_module()
        module._userPhraseWarningShown = False
        conn = sqlite3.connect(ch.config().getUserPhrase())
        conn.execute("CREATE TABLE IF NOT EXISTS lock_test (x)")
        conn.execute("BEGIN EXCLUSIVE")
        try:
            service = module.ChewingTextService(ch.DummyClient())
            ch._services.append(service)
            reply = ch.request(service, "onActivate", isKeyboardOpen=True)
            self.assertIsNotNone(service.chewingContext)  # NULL (ctx 0) before, every key swallowed
            self.assertTrue(service.userPhraseFallback)
            self.assertIn("showMessage", reply)
            self.assertEqual(self.type(service, list("su3") + ["ENTER"]), "你")  # typing still works
        finally:
            conn.rollback()
            conn.close()
        # the next activation retries the real database
        ch.request(service, "onDeactivate")
        ch.request(service, "onActivate", isKeyboardOpen=True)
        self.assertFalse(service.userPhraseFallback)

    def test_no_context_at_all_passes_keys_through(self):
        module = ch.load_module()
        saved = module.CHEWING_DATA_DIR
        module.CHEWING_DATA_DIR = os.path.join(tempfile.gettempdir(), "no-such-chewing-data")
        try:
            s = self.service()
        finally:
            module.CHEWING_DATA_DIR = saved
        self.assertIsNone(s.chewingContext)
        for key in "su3":
            self.assertFalse(ch.request(s, "filterKeyDown", **ch.key_event(key)).get("return"))
        # retried when the keyboard is opened again
        ch.request(s, "onKeyboardStatusChanged", opened=False)
        ch.request(s, "onKeyboardStatusChanged", opened=True)
        self.assertIsNotNone(s.chewingContext)


class EngineFaultTests(ChewingTestCase):
    def test_native_fault_rebuilds_the_context(self):
        s = self.service()
        self.type(s, list("su3"))
        old = s.chewingContext

        def fault(*args):
            raise libchewing.ChewingFault("exception: access violation reading 0x00000004")
        old.handle_Default = fault
        down = ch.key_event("j")
        self.assertTrue(ch.request(s, "filterKeyDown", **down).get("return"))
        reply = ch.request(s, "onKeyDown", **down)  # a BackendError (pipe reset) before
        self.assertTrue(reply["success"])
        self.assertIsNot(s.chewingContext, old)
        self.assertEqual(reply.get("compositionString"), "")
        self.assertIn("showMessage", reply)
        self.assertFalse(s.isComposing())
        self.assertEqual(self.type(s, list("su3") + ["ENTER"]), "你")

    def test_modes_survive_a_fault(self):
        s = self.service()
        self.type(s, ["SHIFT"])  # English
        ch.request(s, "onPreservedKey", guid=SHIFT_SPACE_GUID)  # full shape
        self.assertEqual((s.langMode, s.shapeMode), (0, 1))

        def fault(*args):
            raise libchewing.ChewingFault("exception: access violation reading 0x00000004")
        s.chewingContext.handle_Default = fault
        ch.type_keys(s, ["a"])
        self.assertEqual(s.chewingContext.get_ChiEngMode(), 0)
        self.assertEqual(s.chewingContext.get_ShapeMode(), 1)

    def test_known_crashing_sequences_do_not_raise(self):
        # the bundled chewing.dll faults on these (found by the audit fuzzer)
        cases = [
            (dict(keyboardLayout=1), ["k", "SPACE", "4", "k", "SPACE"]),
            (dict(keyboardLayout=5), ["j", "SPACE", "SPACE", "2", "s", "SPACE"]),
            (dict(), list("8484") + ["HOME", "j", "6", "LEFT", "DEL", "DOWN", "3"]),
        ]
        for overrides, keys in cases:
            with self.subTest(keys=" ".join(keys)):
                s = self.service(**overrides)
                self.type(s, keys)
                self.type(s, ["ESC", "ESC"])
                self.assertIsNotNone(s.chewingContext)


class DataReloadTests(ChewingTestCase):
    def write_user_file(self, name, text):
        path = os.path.join(config_dir(), name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        stamp = time.time() + 10
        os.utime(path, (stamp, stamp))
        force_config_check()

    def test_reload_waits_until_the_composition_ends(self):
        s = self.service()
        ch.request(s, "onPreservedKey", guid=SHIFT_SPACE_GUID)  # full shape
        self.type(s, list("su3"))
        old = s.chewingContext
        self.write_user_file("swkb.dat", "Q ★\n")
        self.type(s, list("ji3"))
        self.assertIs(s.chewingContext, old)  # the pending 你 used to be dropped here
        self.assertEqual(self.type(s, ["ENTER"]), "你我")
        ch.request(s, "onKillFocus")  # not composing any more: rebuilt now
        self.assertIsNot(s.chewingContext, old)
        self.assertEqual(s.chewingContext.get_ShapeMode(), 1)  # reset to half shape before
        self.assertEqual(self.type(s, [("Q", "S")]), "")
        self.assertEqual(s.compositionString, "★")  # the new swkb.dat is in use

    def test_reload_keeps_english_mode(self):
        s = self.service()
        self.type(s, ["SHIFT"])  # English
        old = s.chewingContext
        self.write_user_file("symbols.dat", "測試=★☆\n")
        ch.request(s, "onKillFocus")
        self.assertIsNot(s.chewingContext, old)
        self.assertEqual(s.chewingContext.get_ChiEngMode(), 0)  # every app went back to Chinese before

    def test_invalid_utf8_from_a_long_symbols_line(self):
        # libchewing reads symbols.dat with a 512-byte buffer: this line is cut
        # in the middle of an emoji
        self.write_user_file("symbols.dat", "長=" + "\U0001F600" * 200 + "\n…\n")
        s = self.service()
        for key in ["`", "1", "1", "s", "u", "3", "ESC", "ESC"]:
            ch.type_keys(s, [key])  # UnicodeDecodeError on every key before


class NonAsciiAppDataTests(ChewingTestCase):
    def ansi_name(self):
        for name in ("\u738b\u5c0f\u660e", "Jos\u00e9", "\u00c5sa", "\u0416\u0435\u043d\u044f"):
            try:
                name.encode("mbcs")
                return name
            except UnicodeEncodeError:
                pass
        self.skipTest("no non-ASCII name fits the ANSI code page")

    def test_user_swkb_is_used_under_a_non_ascii_appdata(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        appdata = os.path.join(root, self.ansi_name())
        saved = os.environ["APPDATA"]
        os.environ["APPDATA"] = appdata
        self.addCleanup(os.environ.__setitem__, "APPDATA", saved)
        os.makedirs(config_dir(), exist_ok=True)
        with open(os.path.join(config_dir(), "swkb.dat"), "w", encoding="utf-8") as f:
            f.write("Q \u2605\n")
        s = self.service(easySymbolsWithShift=True)
        self.type(s, [("Q", "S")])
        self.assertEqual(s.compositionString, "\u2605")  # the shipped swkb.dat gives 〔
        ch.close_all()


if __name__ == "__main__":
    unittest.main()
