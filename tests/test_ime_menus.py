"""The right-click menu of the taskbar IME icon (language bar 設定 button) of
大易/酷倉 and 新酷音: each item that opens a web page must open a working one.

- 網路辭典 → 教育部成語典 opened http://dict.idioms.moe.edu.tw/cydic/, a dead-end
  404 page since the MOE dictionary sites were rebuilt (2021); 國語辭典, 簡編本 and
  小字典 still went through plain-http redirects from the old paths.
- 「WIME 討論區」 opened the same issues page as 「WIME 錯誤回報」 (the repository
  has no GitHub Discussions), so it was removed.

The pages are recorded, not opened (IsolatedAppData replaces os.startfile).
"""

import unittest

import cinbase_harness as h

MOE_DICTIONARIES = {
    "教育部國語辭典": "https://dict.revised.moe.edu.tw/",
    "教育部國語辭典簡編本": "https://dict.concised.moe.edu.tw/",
    "教育部國語小字典": "https://dict.mini.moe.edu.tw/",
    "教育部成語典": "https://dict.idioms.moe.edu.tw/",
}

_appdata = None


def setUpModule():
    global _appdata
    _appdata = h.IsolatedAppData()


def tearDownModule():
    _appdata.close()


def menu_items(menu):
    for item in menu:
        if "submenu" in item:
            yield from menu_items(item["submenu"])
        elif item.get("id"):
            yield item["text"], item["id"]


def opened_pages(service, request):
    """{menu text: page os.startfile opened} for the icon menu's items."""
    menu = request(service, "onMenu", id="windows-mode-icon")["return"]
    pages = {}
    for text, command in menu_items(menu):
        start = len(_appdata.launches)
        request(service, "onCommand", id=command, type=0)
        for name, args in _appdata.launches[start:]:
            if name == "startfile":
                pages[text] = args[0]
    return pages


class MenuPageTestCase(unittest.TestCase):
    def assertWorkingPages(self, pages, dictionaries):
        self.assertTrue(h.launches_blocked())
        for text, url in dictionaries.items():
            self.assertEqual(pages.get(text), url, text)
        duplicates = {url for url in pages.values() if list(pages.values()).count(url) > 1}
        self.assertEqual(duplicates, set(), "two menu items open the same page")


@h.requires_tables
class CinBaseMenuTests(MenuPageTestCase):
    def test_menu_pages(self):
        for ime in ("chedayi", "checj"):
            with self.subTest(ime=ime):
                service = h.make_service(ime)
                h.request(service, "onActivate", isKeyboardOpen=True)
                pages = opened_pages(service, h.request)
                self.assertWorkingPages(pages, MOE_DICTIONARIES)
                self.assertNotIn("WIME 討論區 (&F)", pages)
                for text, url in pages.items():
                    self.assertTrue(url.startswith("https://"), (text, url))


class ChewingMenuTests(MenuPageTestCase):
    @classmethod
    def setUpClass(cls):
        import chewing_harness
        cls.ch = chewing_harness

    def tearDown(self):
        self.ch.close_all()

    def test_dictionary_pages(self):
        service = self.ch.make_service()
        pages = opened_pages(service, self.ch.request)
        # 新酷音的辭典選單沒有國語辭典（完整版）
        dictionaries = {text: url for text, url in MOE_DICTIONARIES.items() if text != "教育部國語辭典"}
        self.assertWorkingPages(pages, dictionaries)


if __name__ == "__main__":
    unittest.main()
