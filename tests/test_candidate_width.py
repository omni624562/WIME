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
Both key styles users end up with are checked: keycap is the backend default
that the first load writes to config.json, and the settings pages always save
word-first.
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
KEY_STYLES = ("keycap", "word-first")
SAMPLE_CANDIDATES = "你七鹿擬虍乙"   # CJK ideographs all have the same advance
FONT_FACE = "Microsoft JhengHei"    # candFontName sent by cinbase and chewing_ime
DEFAULT_GUI_FONT = 17


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
            size = wintypes.SIZE()
            _gdi32.GetTextExtentPoint32W(dc, text, len(text), ctypes.byref(size))
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


def shipped_defaults():
    """{ime: (default settings, selection keys shown with the candidates)}"""
    chewing_config = importlib.import_module("input_methods.chewing.chewing_config")
    chewing = chewing_config.ChewingConfig(load=False)   # does not touch APPDATA
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


if __name__ == "__main__":
    unittest.main()
