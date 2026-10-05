"""選字符 (candidateKeyStyle) and 名稱標籤 (candidateHeaderStyle) of the candidate
window must be what the settings pages show.

The pages offer only Word First and Accent and write them on every save, but
the backends defaulted to keycap / badge: a new install did not look like the
pages' previews, and the first save of anything else (a theme, say) moved every
selection key from a keycap in front of the candidate to after it, and changed
大易/酷倉's name label. 新酷音's first load had already written keycap into
config.json, and it never sent a header style (the C++ default is badge).
Both backends now default to and load only the pages' styles.
"""

import importlib
import json
import os
import time
import unittest

import cinbase_harness as h
from cinbase.config import CinBaseConfig

PAGE_STYLES = {"candidateKeyStyle": "word-first", "candidateHeaderStyle": "accent"}
OLD_STYLES = {"candidateKeyStyle": "keycap", "candidateHeaderStyle": "badge"}

_appdata = None


def setUpModule():
    global _appdata, _real_play
    _appdata = h.IsolatedAppData()
    _real_play = h.cinbase.winsound.PlaySound
    h.cinbase.winsound.PlaySound = lambda *a, **k: None


def tearDownModule():
    h.cinbase.winsound.PlaySound = _real_play
    _appdata.close()


def styles(values):
    return {key: values.get(key) for key in PAGE_STYLES}


class CinBaseStyleTests(unittest.TestCase):
    def tearDown(self):
        for ime in ("chedayi", "checj"):
            h.remove_user_config(ime)

    def fresh_config(self, ime):
        cfg = type(CinBaseConfig)()
        cfg.imeDirName = ime
        cfg.load()
        return cfg

    def test_config_defaults_and_stored_styles(self):
        self.assertEqual(styles(type(CinBaseConfig)().__dict__), PAGE_STYLES)
        for ime in ("chedayi", "checj"):
            with self.subTest(ime=ime):
                self.assertEqual(styles(self.fresh_config(ime).toJson()), PAGE_STYLES)
                h.write_user_config(ime, OLD_STYLES)    # saved before the pages fixed them
                self.assertEqual(styles(self.fresh_config(ime).toJson()), PAGE_STYLES)

    @h.requires_tables
    def test_activation_sends_the_page_styles(self):
        for ime in ("chedayi", "checj"):
            for user_config in (None, OLD_STYLES):
                with self.subTest(ime=ime, user_config=user_config):
                    service = h.make_service(ime, user_config=user_config)
                    reply = h.request(service, "onActivate", isKeyboardOpen=True)
                    self.assertEqual(styles(reply["customizeUI"]), PAGE_STYLES)


class ChewingStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import chewing_harness
        cls.ch = chewing_harness
        cls.cc = importlib.import_module("input_methods.chewing.chewing_config")

    def setUp(self):
        self.path = self.cc.chewingConfig.getConfigFile()
        override = self.ch.ConfigOverride()     # the shared config object is reloaded below
        self.addCleanup(override.restore)
        self.addCleanup(self.ch.close_all)
        self.addCleanup(self.remove_config)

    def remove_config(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def write_config(self, values):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(values, f)
        stamp = time.time() + 10
        os.utime(self.path, (stamp, stamp))

    def test_config_defaults_and_stored_style(self):
        self.assertEqual(self.cc.ChewingConfig(load=False).candidateKeyStyle, "word-first")
        self.remove_config()
        self.cc.ChewingConfig()                 # the first load writes config.json
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["candidateKeyStyle"], "word-first")
        self.write_config({"candidateKeyStyle": "keycap"})
        self.assertEqual(self.cc.ChewingConfig().candidateKeyStyle, "word-first")
        # the settings tool shows the file through normalizeValues
        values = self.cc.normalizeValues({"candidateKeyStyle": "keycap"}, self.cc.defaultValues())
        self.assertEqual(values, {"candidateKeyStyle": "word-first"})

    def test_activation_sends_the_page_styles(self):
        module = self.ch.load_module()
        service = module.ChewingTextService(self.ch.DummyClient())
        self.ch._services.append(service)
        reply = self.ch.request(service, "onActivate", isKeyboardOpen=True)
        self.assertEqual(styles(reply["customizeUI"]), PAGE_STYLES)

        # a config.json the old backend wrote, read again while 新酷音 is active
        self.write_config({"candidateKeyStyle": "keycap", "candPerPage": 7})
        self.ch.config()._lastUpdateTime = None   # skip the 3 s throttle
        reply = self.ch.request(service, "onKillFocus")
        self.assertEqual(self.ch.config().candPerPage, 7)
        self.assertEqual(styles(reply["customizeUI"]), PAGE_STYLES)


if __name__ == "__main__":
    unittest.main()
