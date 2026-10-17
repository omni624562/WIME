"""新酷音 user phrase dictionary across the libchewing upgrade (old C version ->
0.13.1, see python/libchewing/userdict.py), with the real chewing.dll and a
temporary APPDATA.

- The old C libchewing kept the learned/added phrases in chewing.sqlite3
  (userphrase_v1). 0.13 uses chewing.dat; on the first start the old phrases
  must be converted, a backup of the old file made, and the old file left
  exactly as it was so that going back to the previous WIME keeps working.
- libchewing 0.13 converts on its own when it opens a missing chewing.dat next
  to a chewing.sqlite3, but it opens the old file for writing (WAL mode, new
  tables), and one phrase that is not valid UTF-8 makes it fail completely.
- A failed conversion must not leave an empty chewing.dat behind (the phrases
  would never be converted again) nor let libchewing touch the old file.
"""

import hashlib
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing

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


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def legacy_rows(path):
    with closing(sqlite3.connect(path)) as conn:
        return sorted(conn.execute("SELECT * FROM userphrase_v1").fetchall())


def tables(path):
    with closing(sqlite3.connect(path)) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


class UserDictTestCase(unittest.TestCase):
    def setUp(self):
        # a fresh %APPDATA% for each test (chewingConfig reads it on every call)
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        saved = os.environ["APPDATA"]
        os.environ["APPDATA"] = os.path.join(self.root, "Roaming")
        self.addCleanup(os.environ.__setitem__, "APPDATA", saved)
        self.addCleanup(ch.close_all)
        self.dir = ch.config().getConfigDir()
        self.legacy = os.path.join(self.dir, "chewing.sqlite3")
        self.dat = os.path.join(self.dir, "chewing.dat")
        self.syspath = libchewing.searchPath(self.dir, libchewing.CHEWING_DATA_DIR)

    def service(self):
        override = ch.ConfigOverride()
        self.addCleanup(override.restore)
        return ch.make_service()

    def phrases_in(self, path):
        ctx = libchewing.ChewingContext(syspath=self.syspath, userpath=path, userdir=os.path.dirname(path))
        try:
            return dict(ctx.userPhrases())
        finally:
            ctx.close()

    def type(self, service, keys):
        commits, _ = ch.type_keys(service, keys)
        return "".join(commits)


class MigrationTests(UserDictTestCase):
    def test_old_phrases_are_converted_and_the_old_file_is_kept(self):
        ch.make_legacy_user_db(self.legacy)
        before_hash, before_rows = sha256(self.legacy), legacy_rows(self.legacy)

        s = self.service()  # the IME's first start after the upgrade
        self.assertFalse(s.userPhraseFallback)
        self.assertTrue(os.path.exists(self.dat))
        self.assertEqual(dict(s.chewingContext.userPhrases()), ch.LEGACY_READINGS)
        # an added phrase is used: ㄨㄤˊ ㄒㄧㄠˇ ㄇㄧㄥˊ
        self.assertEqual(self.type(s, list("j;6vul3au/6") + ["ENTER"]), "王小明")
        ch.close_all()

        # the old file is untouched (the previous WIME can still use it) and backed up
        self.assertEqual(sha256(self.legacy), before_hash)
        self.assertEqual(tables(self.legacy), {"userphrase_v1", "config_v1"})
        backup = os.path.join(self.dir, libchewing.LEGACY_BACKUP_NAME)
        self.assertEqual(legacy_rows(backup), before_rows)
        self.assertFalse([name for name in os.listdir(self.dir) if name.startswith("migrate_")])

        # the converted dictionary keeps the phrases on its own
        self.assertEqual(self.phrases_in(self.dat), ch.LEGACY_READINGS)

    def test_phrases_learned_after_the_upgrade_stay_out_of_the_old_file(self):
        ch.make_legacy_user_db(self.legacy)
        before_hash = sha256(self.legacy)
        s = self.service()
        self.assertEqual(s.chewingContext.userphrase_add("詞庫".encode(), "ㄘˊ ㄎㄨˋ".encode()), 1)
        ch.close_all()
        self.assertIn("詞庫", self.phrases_in(self.dat))
        self.assertEqual(sha256(self.legacy), before_hash)  # downgrade: the old version reads this
        # starting again does not convert (and overwrite) a second time
        self.service()
        ch.close_all()
        self.assertIn("詞庫", self.phrases_in(self.dat))

    def test_a_phrase_that_is_not_utf8_does_not_block_the_conversion(self):
        ch.make_legacy_user_db(self.legacy)
        with closing(sqlite3.connect(self.legacy)) as conn:
            conn.execute("UPDATE userphrase_v1 SET phrase = CAST(X'E6B8ACFF' AS TEXT) WHERE phrase = '的'")
            conn.commit()
        before_hash = sha256(self.legacy)
        path = libchewing.prepareUserDictionary(self.dir, self.syspath)
        expected = dict(ch.LEGACY_READINGS)
        del expected["的"]
        self.assertEqual(self.phrases_in(path), expected)
        self.assertEqual(sha256(self.legacy), before_hash)

    def test_a_failed_conversion_changes_nothing(self):
        with open(self.legacy, "wb") as f:
            f.write(b"SQLite format 3\x00" + b"\x00" * 200)  # damaged
        before_hash = sha256(self.legacy)
        with self.assertRaises(libchewing.UserDictionaryError):
            libchewing.prepareUserDictionary(self.dir, self.syspath)
        self.assertFalse(os.path.exists(self.dat))  # tried again next time
        # the IME still types, with an in-memory dictionary, and says so
        module = ch.load_module()
        module._userPhraseWarningShown = False
        s = self.service()
        self.assertTrue(s.userPhraseFallback)
        self.assertEqual(self.type(s, list("su3") + ["ENTER"]), "你")
        ch.close_all()
        self.assertFalse(os.path.exists(self.dat))
        self.assertEqual(sha256(self.legacy), before_hash)
        self.assertFalse([name for name in os.listdir(self.dir) if name.startswith("migrate_")])

    def test_an_empty_old_file_is_left_alone(self):
        open(self.legacy, "wb").close()  # created but never written by the old version
        path = libchewing.prepareUserDictionary(self.dir, self.syspath)
        self.assertEqual(self.phrases_in(path), {})
        self.assertEqual(os.path.getsize(self.legacy), 0)  # libchewing did not "convert" it in place

    def test_an_existing_chewing_dat_wins(self):
        ctx = libchewing.ChewingContext(syspath=self.syspath, userpath=self.dat, userdir=self.dir)
        ctx.userphrase_add("新的".encode(), "ㄒㄧㄣ ㄉㄜ˙".encode())
        ctx.close()
        ch.make_legacy_user_db(self.legacy)
        self.assertEqual(libchewing.prepareUserDictionary(self.dir, self.syspath), self.dat)
        self.assertEqual(self.phrases_in(self.dat), {"新的": "ㄒㄧㄣ ㄉㄜ˙"})
        self.assertFalse(os.path.exists(os.path.join(self.dir, libchewing.LEGACY_BACKUP_NAME)))

    def test_no_old_file_starts_an_empty_dictionary(self):
        s = self.service()
        self.assertFalse(s.userPhraseFallback)
        self.assertEqual(s.chewingContext.userPhrases(), [])
        ch.close_all()
        self.assertTrue(os.path.exists(self.dat))
        self.assertFalse(os.path.exists(self.legacy))


class UserPhraseKeyTests(UserDictTestCase):
    """Ctrl+Del / Ctrl+PageUp / Ctrl+PageDown on a candidate (used to be SQL on
    userphrase_v1, which libchewing 0.13 no longer has)."""

    def candidates_for(self, s, keys):
        self.type(s, list(keys) + ["HOME", "DOWN"])  # phrases starting at the 1st syllable
        return list(s.candidateList)

    def test_ctrl_delete_removes_a_user_phrase(self):
        s = self.service()
        ctx = s.chewingContext
        self.assertEqual(ctx.userphrase_add("測試".encode(), "ㄘㄜˋ ㄕˋ".encode()), 1)
        cands = self.candidates_for(s, "hk4g4")  # ㄘㄜˋ ㄕˋ
        self.assertIn("測試", cands)
        s.setCandidateCursor(cands.index("測試"))
        reply = ch.press(s, "DEL", ctrl=True)
        self.assertIn("刪除「測試」成功", str(reply))
        self.assertNotIn("測試", dict(ctx.userPhrases()))

    def test_ctrl_page_down_keeps_a_phrase_only_the_user_has(self):
        s = self.service()
        ctx = s.chewingContext
        self.assertEqual(ctx.userphrase_add("測測".encode(), "ㄘㄜˋ ㄘㄜˋ".encode()), 1)
        cands = self.candidates_for(s, "hk4hk4")
        self.assertIn("測測", cands)
        s.setCandidateCursor(cands.index("測測"))
        reply = ch.press(s, "PGDN", ctrl=True)
        self.assertIn("自訂詞", str(reply))
        self.assertIn("測測", dict(ctx.userPhrases()))  # not deleted by "lower the frequency"


    def test_ctrl_page_up_and_down_on_a_dictionary_phrase(self):
        s = self.service()
        ctx = s.chewingContext
        self.assertEqual(ctx.userphrase_add("測試".encode(), "ㄘㄜˋ ㄕˋ".encode()), 1)
        cands = self.candidates_for(s, "hk4g4")
        s.setCandidateCursor(cands.index("測試"))
        self.assertIn("提昇「測試」詞頻成功", str(ch.press(s, "PGUP", ctrl=True)))
        self.assertIn("測試", dict(ctx.userPhrases()))
        # lowering forgets what was learned; the built-in dictionary still has it
        self.assertIn("降低「測試」詞頻成功", str(ch.press(s, "PGDN", ctrl=True)))
        self.assertNotIn("測試", dict(ctx.userPhrases()))
        self.assertIn("不存在", str(ch.press(s, "PGDN", ctrl=True)))

if __name__ == "__main__":
    unittest.main()
