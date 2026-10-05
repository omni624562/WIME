#! python3
"""候選窗一列實際排得下幾個候選 (libIME2 CandidateWindow::recalculateSize() 的欄數)。

候選窗開著「超過最大寬度自動換行」(預設) 時，每一欄的寬度是這一頁最寬的候選
加上最寬的選字鍵，一列放不下 candPerRow 個就換行：新酷音預設的 16pt、340px，
一頁單字排得下 6 個，兩個字的詞只排得下 4 個、三個字的 3 個；把每列字數調到
7～10 也還是 6 個。新酷音的上下鍵以前一律移 candidatePerRow 格，落到別欄或完全
不動。這裡用候選窗同樣的字型 (PIMETextService：DEFAULT_GUI_FONT 換成指定字型、
lfHeight = -MulDiv(字級, dpi, 72)、FW_NORMAL) 量字寬，照 recalculateSize() 算欄數。
tests/test_candidate_width.py 另有一份同樣的模型，與 C++ 一起改。

後端不知道候選窗在哪個螢幕，用系統 DPI：支援 DPI 的程式 (大多數) 在單一螢幕上
就是這個值。字型與間距都隨 DPI 等比放大，換算誤差只在剛好卡在邊界的設定。
"""

import ctypes
from ctypes import wintypes

FONT_NAME = "Microsoft JhengHei"  # 新酷音送出的 candFontName
DEFAULT_GUI_FONT = 17
FW_NORMAL = 400
DPI_AWARENESS_CONTEXT_SYSTEM_AWARE = -2


class _LOGFONTW(ctypes.Structure):
    _fields_ = [("lfHeight", wintypes.LONG), ("lfWidth", wintypes.LONG),
                ("lfEscapement", wintypes.LONG), ("lfOrientation", wintypes.LONG),
                ("lfWeight", wintypes.LONG), ("lfItalic", wintypes.BYTE),
                ("lfUnderline", wintypes.BYTE), ("lfStrikeOut", wintypes.BYTE),
                ("lfCharSet", wintypes.BYTE), ("lfOutPrecision", wintypes.BYTE),
                ("lfClipPrecision", wintypes.BYTE), ("lfQuality", wintypes.BYTE),
                ("lfPitchAndFamily", wintypes.BYTE), ("lfFaceName", wintypes.WCHAR * 32)]


# 自己的 WinDLL：在 ctypes.windll 的函式上設定 argtypes 會影響其他模組的呼叫
_gdi32 = ctypes.WinDLL("gdi32")
_user32 = ctypes.WinDLL("user32")
_user32.GetDC.argtypes = [wintypes.HWND]
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_gdi32.GetStockObject.argtypes = [ctypes.c_int]
_gdi32.GetStockObject.restype = wintypes.HGDIOBJ
_gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
_gdi32.CreateFontIndirectW.argtypes = [ctypes.POINTER(_LOGFONTW)]
_gdi32.CreateFontIndirectW.restype = wintypes.HFONT
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi32.GetTextExtentPoint32W.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
                                         ctypes.POINTER(wintypes.SIZE)]


def mulDiv(value, numerator, denominator):
    """Win32 MulDiv() for value >= 0 (四捨五入)"""
    return (value * numerator + denominator // 2) // denominator


def systemDpi():
    """系統 DPI。後端行程沒有宣告 DPI 感知，直接問只會得到 96，所以暫時讓這條
    執行緒感知系統 DPI 再問 (Windows 10 1607 起才有這些函式，之前的版本用 96)"""
    try:
        setContext = _user32.SetThreadDpiAwarenessContext
        getDpi = _user32.GetDpiForSystem
    except AttributeError:
        return 96
    setContext.argtypes = [ctypes.c_void_p]
    setContext.restype = ctypes.c_void_p
    getDpi.restype = wintypes.UINT
    old = setContext(ctypes.c_void_p(DPI_AWARENESS_CONTEXT_SYSTEM_AWARE))
    try:
        dpi = getDpi()
    finally:
        if old:
            setContext(ctypes.c_void_p(old))
    return dpi or 96


def utf16Length(text):
    """text 的 UTF-16 長度。GetTextExtentPoint32W 的字數是 UTF-16 單位，C++ 傳的是
    wstring::length()；len() 算的是字元數，BMP 以外的字 (詞庫裡的 CJK 擴充 B 區字、
    特殊符號裡的表情符號) 只量到前半個代理字元，寬度少一半，算出的欄數比畫面多。
    surrogatepass：單獨的代理字元 ctypes 也照樣傳一個單位"""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def measureTexts(fontName, fontSize, dpi, texts):
    """{文字: 寬度 (px)}，字型照 PIMETextService 建立；失敗時傳回 None"""
    lf = _LOGFONTW()
    if not _gdi32.GetObjectW(_gdi32.GetStockObject(DEFAULT_GUI_FONT), ctypes.sizeof(lf), ctypes.byref(lf)):
        return None
    lf.lfHeight = -mulDiv(fontSize, dpi, 72)
    lf.lfWeight = FW_NORMAL
    lf.lfFaceName = fontName[:31]
    font = _gdi32.CreateFontIndirectW(ctypes.byref(lf))
    if not font:
        return None
    dc = _user32.GetDC(None)
    if not dc:
        _gdi32.DeleteObject(font)
        return None
    old = _gdi32.SelectObject(dc, font)
    try:
        widths = {}
        size = wintypes.SIZE()
        for text in texts:
            if text not in widths:
                if not _gdi32.GetTextExtentPoint32W(dc, text, utf16Length(text), ctypes.byref(size)):
                    return None
                widths[text] = size.cx
        return widths
    finally:
        _gdi32.SelectObject(dc, old)
        _user32.ReleaseDC(None, dc)
        _gdi32.DeleteObject(font)


# CandidateWindow.cpp 的 modernCandidateKeyMinWidth() 與 modernCandidateExtraWidth()。
# 設定頁只提供 word-first 選字符 (兩個設定檔載入時都固定成它)；keycap 是 C++ 的預設
def _keyMinWidth(keyStyle, textMargin):
    return max(17, textMargin * 3 + 5) if keyStyle == "keycap" else 0


def _extraItemWidth(keyStyle, textMargin):
    textGap = 1 if keyStyle == "keycap" else max(3, textMargin // 2)
    return textMargin * 2 + textGap + max(2, textMargin // 2)


def candidateColumns(candidates, selKeys, perRow, fontSize, maxWidth, wrapToMaxWidth=True,
                     contentMargin=8, textMargin=6, keyStyle="word-first", fontName=FONT_NAME, dpi=None):
    """這一頁的 candidates 在候選窗一列排幾個 (1～perRow)。contentMargin / textMargin
    是送給候選窗的 candidateStyle (沒送時 C++ 用 8 / 6)；量不到字寬時傳回 perRow"""
    perRow = max(1, perRow)
    if perRow == 1 or not wrapToMaxWidth or maxWidth <= 0 or not candidates:
        return perRow
    if dpi is None:
        dpi = systemDpi()
    keys = [selKeys[i] for i in range(min(len(candidates), len(selKeys)))]
    try:
        widths = measureTexts(fontName, fontSize, dpi, keys + list(candidates))
    except (OSError, ValueError, ctypes.ArgumentError):
        widths = None
    if not widths:
        return perRow

    def scale(value):  # TextService::scaleForCandDpi()
        return value if dpi == 96 else mulDiv(value, dpi, 96)

    margin = scale(contentMargin)
    textMargin = scale(textMargin)
    colSpacing = max(6, textMargin + 2)
    keyWidth = max([widths[key] for key in keys] + [_keyMinWidth(keyStyle, textMargin)])
    textWidth = max(widths[text] for text in candidates)
    stride = keyWidth + textWidth + _extraItemWidth(keyStyle, textMargin)
    contentLimit = max(1, scale(maxWidth) - margin * 2)
    return max(1, min(perRow, (contentLimit + colSpacing) // (stride + colSpacing)))
