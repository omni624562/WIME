"""The default candidateMaxWidth must fit a full row of single-character
candidates with each input method's default font, at the usual Windows scales.

CandidateWindow (libIME2/src/CandidateWindow.cpp recalculateSize()) puts fewer
than candidatePerRow candidates on a row when the row would be wider than
candidateMaxWidth. The old default 300 was too narrow at 100% scaling: a page
of six 大易/酷倉 candidates (12pt) needs 306px and showed 5+1, and 新酷音 (16pt)
needs 336px, so its 9 candidates showed 5+4 even with 320.

This redoes recalculateSize()'s column math with the real glyph widths,
measured through GDI with the font PIMETextService creates
(DEFAULT_GUI_FONT with lfHeight -MulDiv(size, dpi, 72), Microsoft JhengHei) and
the spacing scaled by MulDiv(value, dpi, 96) (TextService::scaleForCandDpi()).
Keep it in sync with recalculateSize() and the modernCandidate*() helpers.
The selection keys are always drawn word-first: it is the only style the
settings pages offer, and both backends load any stored style as word-first.
The old-width check uses keycap, the backend default the 5+1 / 5+4 rows were
seen with.
"""

import ctypes
import importlib
import json
import os
import unittest
from ctypes import wintypes

import cinbase_harness as h
from cinbase import selkeys

DPIS = (96, 120, 144, 168, 192)     # 100% .. 200%
KEY_STYLES = ("word-first",)
SAMPLE_CANDIDATES = "你七鹿擬虍乙"   # CJK ideographs all have the same advance
FONT_FACE = "Microsoft JhengHei"    # candFontName sent by cinbase and chewing_ime
DEFAULT_GUI_FONT = 17

_appdata = None


def setUpModule():
    # importing chewing_config creates its shared config object, which loads (and
    # may write) %APPDATA%\PIME\chewing; ChewingConfig(load=False) alone does not
    global _appdata
    _appdata = h.IsolatedAppData()


def tearDownModule():
    _appdata.close()


class LOGFONTW(ctypes.Structure):
    _fields_ = [("lfHeight", wintypes.LONG), ("lfWidth", wintypes.LONG),
                ("lfEscapement", wintypes.LONG), ("lfOrientation", wintypes.LONG),
                ("lfWeight", wintypes.LONG), ("lfItalic", wintypes.BYTE),
                ("lfUnderline", wintypes.BYTE), ("lfStrikeOut", wintypes.BYTE),
                ("lfCharSet", wintypes.BYTE), ("lfOutPrecision", wintypes.BYTE),
                ("lfClipPrecision", wintypes.BYTE), ("lfQuality", wintypes.BYTE),
                ("lfPitchAndFamily", wintypes.BYTE), ("lfFaceName", wintypes.WCHAR * 32)]


# private WinDLL objects: setting argtypes on ctypes.windll's would change them
# for the IME code under test too
_gdi32 = ctypes.WinDLL("gdi32")
_user32 = ctypes.WinDLL("user32")
_kernel32 = ctypes.WinDLL("kernel32")
_user32.GetDC.argtypes = [wintypes.HWND]
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_gdi32.GetStockObject.argtypes = [ctypes.c_int]
_gdi32.GetStockObject.restype = wintypes.HGDIOBJ
_gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
_gdi32.CreateFontIndirectW.argtypes = [ctypes.POINTER(LOGFONTW)]
_gdi32.CreateFontIndirectW.restype = wintypes.HFONT
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi32.GetTextExtentPoint32W.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
                                         ctypes.POINTER(wintypes.SIZE)]
_gdi32.GetTextFaceW.argtypes = [wintypes.HDC, ctypes.c_int, wintypes.LPWSTR]
_kernel32.MulDiv.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]


def mul_div(value, numerator, denominator):
    return _kernel32.MulDiv(value, numerator, denominator)


def _measure(face_name, font_size, dpi, texts):
    """(face GDI picked, {text: width in px}), the font made like TextService does"""
    lf = LOGFONTW()
    _gdi32.GetObjectW(_gdi32.GetStockObject(DEFAULT_GUI_FONT), ctypes.sizeof(lf), ctypes.byref(lf))
    lf.lfHeight = -mul_div(font_size, dpi, 72)
    lf.lfWeight = 400   # FW_NORMAL
    lf.lfFaceName = face_name
    font = _gdi32.CreateFontIndirectW(ctypes.byref(lf))
    dc = _user32.GetDC(None)
    old = _gdi32.SelectObject(dc, font)
    try:
        face = ctypes.create_unicode_buffer(32)
        _gdi32.GetTextFaceW(dc, len(face), face)
        widths = {}
        for text in texts:
            # the length in UTF-16 units, like C++ passes wstring::length(): len()
            # counts a character outside the BMP (CJK Ext-B, emoji) once, and GDI
            # then measures only its first surrogate
            buffer = ctypes.create_unicode_buffer(text)
            size = wintypes.SIZE()
            _gdi32.GetTextExtentPoint32W(dc, buffer, len(buffer) - 1, ctypes.byref(size))
            widths[text] = size.cx
        return face.value, widths
    finally:
        _gdi32.SelectObject(dc, old)
        _user32.ReleaseDC(None, dc)
        _gdi32.DeleteObject(font)


def measure(font_size, dpi, texts):
    """{text: width in px} with the candidate window font, or None when the font
    is not installed. GetTextFaceW returns localized names (微軟正黑體), so compare
    with the substitute GDI picks for a name that does not exist."""
    face, widths = _measure(FONT_FACE, font_size, dpi, texts)
    if face == _measure("WIME no such font", font_size, dpi, ())[0]:
        return None
    return widths


def key_min_width(key_style, text_margin):     # modernCandidateKeyMinWidth()
    return max(17, text_margin * 3 + 5) if key_style == "keycap" else 0


def extra_item_width(key_style, text_margin):  # modernCandidateExtraWidth()
    text_gap = 1 if key_style == "keycap" else max(3, text_margin // 2)
    return text_margin * 2 + text_gap + max(2, text_margin // 2)


def row_layout(cfg, keys, key_style, dpi, max_width):
    """(columns per row, px a full row needs) for a page of single characters."""
    per_row = cfg["candidatePerRow"]
    keys = keys[:per_row]
    widths = measure(cfg["fontSize"], dpi, list(keys) + list(SAMPLE_CANDIDATES))
    if widths is None:
        raise unittest.SkipTest("%s is not installed" % FONT_FACE)
    margin = mul_div(cfg["candidateStyle"]["contentMargin"], dpi, 96)
    text_margin = mul_div(cfg["candidateStyle"]["textMargin"], dpi, 96)
    col_spacing = max(6, text_margin + 2)
    key_width = max(max(widths[key] for key in keys), key_min_width(key_style, text_margin))
    text_width = max(widths[char] for char in SAMPLE_CANDIDATES)
    stride = key_width + text_width + extra_item_width(key_style, text_margin)
    content_limit = max(1, mul_div(max_width, dpi, 96) - margin * 2)
    columns = min(per_row, (content_limit + col_spacing) // (stride + col_spacing))
    needed = per_row * stride + (per_row - 1) * col_spacing + margin * 2
    return columns, needed


def page_columns(font_size, per_row, keys, candidates, key_style, dpi, max_width,
                 content_margin=6, text_margin=4):
    """Columns recalculateSize() gives a page of any candidates: the stride is the
    widest candidate and the widest selection key of the page."""
    keys = keys[:len(candidates)]
    widths = measure(font_size, dpi, list(keys) + list(candidates))
    if widths is None:
        raise unittest.SkipTest("%s is not installed" % FONT_FACE)
    margin = mul_div(content_margin, dpi, 96)
    text_margin = mul_div(text_margin, dpi, 96)
    col_spacing = max(6, text_margin + 2)
    key_width = max(max(widths[key] for key in keys), key_min_width(key_style, text_margin))
    stride = key_width + max(widths[text] for text in candidates) + extra_item_width(key_style, text_margin)
    content_limit = max(1, mul_div(max_width, dpi, 96) - margin * 2)
    return max(1, min(per_row, (content_limit + col_spacing) // (stride + col_spacing)))


def shipped_defaults():
    """{ime: (default settings, selection keys shown with the candidates)}"""
    chewing_config = importlib.import_module("input_methods.chewing.chewing_config")
    chewing = chewing_config.ChewingConfig(load=False)   # the shipped defaults, not the file's
    defaults = {"chewing": (chewing.toJson(), chewing.getSelKeys())}
    for ime, keys in (("chedayi", selkeys.DAYI_CAND_SELKEYS), ("checj", selkeys.DEFAULT_SELKEYS)):
        path = os.path.join(h.PYTHON_DIR, "input_methods", ime, "config", "config.json")
        with open(path, encoding="utf-8-sig") as f:
            defaults[ime] = (json.load(f), keys)
    return defaults


class CandidateMaxWidthTests(unittest.TestCase):
    def test_default_layout_settings_are_modelled(self):
        for ime, (cfg, _) in shipped_defaults().items():
            with self.subTest(ime=ime):
                self.assertTrue(cfg["candidateWrapToMaxWidth"])
                self.assertIn(cfg["candidateKeyStyle"], KEY_STYLES)

    def test_default_max_width_fits_a_full_row(self):
        for ime, (cfg, keys) in shipped_defaults().items():
            for key_style in KEY_STYLES:
                for dpi in DPIS:
                    with self.subTest(ime=ime, key_style=key_style, dpi=dpi):
                        columns, needed = row_layout(cfg, keys, key_style, dpi, cfg["candidateMaxWidth"])
                        self.assertEqual(columns, cfg["candidatePerRow"],
                                         "a full row needs %dpx at %d dpi" % (needed, dpi))

    def test_old_max_widths_wrapped(self):
        # the model reproduces what the real CandidateWindow showed at 100%
        defaults = shipped_defaults()
        for ime, (cfg, keys) in defaults.items():
            with self.subTest(ime=ime):
                columns, _ = row_layout(cfg, keys, "keycap", 96, 300)
                self.assertEqual(columns, cfg["candidatePerRow"] - 1)
        cfg, keys = defaults["chewing"]
        columns, needed = row_layout(cfg, keys, "keycap", 96, 320)
        self.assertEqual((columns, needed), (5, 336))


class BackendColumnTests(unittest.TestCase):
    """python/candidate_layout.py, which 新酷音's ↑/↓ step by, computes the same
    columns as this model. A page of phrases is wider: at the default 16pt and
    340px, two-character phrases show 4 to a row and three-character ones 3.
    Characters outside the BMP are two UTF-16 units: the libchewing dictionary
    has CJK Ext-B characters, and 特殊符號 can hold emoji. The backend measured
    only their first surrogate (half the width) and counted too many columns."""

    PAGES = (list(SAMPLE_CANDIDATES), ["意義", "異議", "熠熠", "奕奕", "意譯", "異義", "易易", "悒悒", "義役"],
             ["新酷音", "心酷音", "新苦音", "欣酷音"], ["你", "妳", "中華民國"],
             [chr(0x1F600 + i) for i in range(9)],                  # emoji
             [chr(0x1F600) * 2, chr(0x1F601) * 2, chr(0x1F602)],
             list("你妳擬鹿七乙虍") + [chr(0x2010C), "倪"])         # one Ext-B character

    def test_columns_match_the_model(self):
        import candidate_layout
        keys = "1234567890"
        checked = 0
        for dpi in DPIS:
            for font_size in (12, 16, 20):
                for per_row in (1, 6, 9):
                    for max_width in (220, 340, 500):
                        for key_style in ("word-first", "keycap"):
                            for page in self.PAGES:
                                expected = page_columns(font_size, per_row, keys, page, key_style, dpi, max_width)
                                got = candidate_layout.candidateColumns(
                                    page, keys, per_row, font_size, max_width, True, 6, 4, key_style, dpi=dpi)
                                if got != expected:
                                    self.fail("%r at %dpt, %d per row, %dpx, %s, %d dpi: %d, not %d" % (
                                        page, font_size, per_row, max_width, key_style, dpi, got, expected))
                                checked += 1
        self.assertGreater(checked, 0)

    def test_phrases_at_the_chewing_defaults(self):
        import candidate_layout
        cfg, keys = shipped_defaults()["chewing"]
        style = cfg["candidateStyle"]
        for dpi in DPIS:
            with self.subTest(dpi=dpi):
                columns = [candidate_layout.candidateColumns(
                    page, keys, cfg["candidatePerRow"], cfg["fontSize"], cfg["candidateMaxWidth"],
                    cfg["candidateWrapToMaxWidth"], style["contentMargin"], style["textMargin"],
                    cfg["candidateKeyStyle"], dpi=dpi) for page in self.PAGES[:3]]
                self.assertEqual(columns, [6, 4, 3])

    def test_no_wrapping(self):
        import candidate_layout
        for args in ((True, 0), (False, 340)):
            self.assertEqual(candidate_layout.candidateColumns(
                self.PAGES[1], "1234567890", 6, 16, args[1], args[0], dpi=96), 6)
        self.assertEqual(candidate_layout.candidateColumns([], "1234567890", 6, 16, 340, dpi=96), 6)


if __name__ == "__main__":
    unittest.main()
