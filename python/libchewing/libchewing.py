#
# Copyright (C) libchewing developers
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

from ctypes import *
import os
import sys

_libchewing = None
if sys.platform == "win32": # Windows
    import os.path
    # find in current dir first
    dll_path = os.path.join(os.path.dirname(__file__), "chewing.dll")
    if not os.path.exists(dll_path):
        dll_path = "chewing.dll" # search in system path
    _libchewing = CDLL(dll_path)
else: # UNIX-like systems
    _libchewing = CDLL('libchewing.so.3')

_libchewing.chewing_commit_String_static.restype = c_char_p
_libchewing.chewing_buffer_String_static.restype = c_char_p
_libchewing.chewing_cand_String_static.restype = c_char_p
_libchewing.chewing_cand_string_by_index_static.restype = c_char_p
_libchewing.chewing_bopomofo_String_static.restype = c_char_p
_libchewing.chewing_aux_String_static.restype = c_char_p
_libchewing.chewing_kbtype_String_static.restype = c_char_p
_libchewing.chewing_version.restype = c_char_p
# the context is a pointer: the default c_int return type truncates it on 64-bit
_libchewing.chewing_new.restype = c_void_p
_libchewing.chewing_new2.restype = c_void_p
_libchewing.chewing_new3.restype = c_void_p
_libchewing.chewing_new3.argtypes = [c_char_p, c_char_p, c_char_p, c_void_p, c_void_p]
_libchewing.chewing_set_logger.argtypes = [c_void_p, c_void_p, c_void_p]

# libchewing 0.13 (Rust) 的 log 回呼：void logger(void *data, int level, const char *fmt, ...)。
# 實際上一律以 ("%s\n", 訊息) 呼叫，所以宣告成兩個字串參數 (cdecl 由呼叫端清堆疊，
# 多宣告或少宣告參數都安全)
_LOGGER = CFUNCTYPE(None, c_void_p, c_int, c_char_p, c_char_p)
LOG_ERROR = 5

# 只載入內建的字庫與詞庫。chewing_new2() 的預設清單還有 chewing.dat 與
# chewing-deleted.dat：
# - chewing.dat 會在搜尋路徑 (含使用者設定目錄) 裡被當成第二份使用者詞庫再載入一次
#   (第一次建立詞庫時)，兩份各自寫回同一個檔案；
# - chewing-deleted.dat (排除清單) 會讓刪除使用者詞時，連內建詞庫裡的同一個詞也一起
#   被隱藏、而且設定工具看不到也救不回來。舊版只刪使用者詞庫裡的那一筆，維持舊版行為。
SYSTEM_DICTIONARIES = b"word.dat,tsi.dat"

# chewing_new3() 在詞庫有問題時不會傳回 NULL (舊版會)，而是改用記憶體中的使用者詞庫、
# 或內建的迷你詞庫，只記一筆錯誤。以這些錯誤訊息判斷建立是否成功
_USER_DICT_FAILED = b"Failed to load user dict"
_SYSTEM_DICT_FAILED = b"Failed to load any system dictionaries"


def version():
    """libchewing 的版本字串，例如 "0.13.1" """
    return _libchewing.chewing_version().decode("ascii")


def encodePath(path):
    """把路徑轉成 libchewing 要的 bytes。0.13 的路徑 (syspath、userpath) 一律是 UTF-8；
    舊的 C 版資料檔路徑要用系統字碼頁。已經是 bytes 的原樣傳回"""
    if path is None or isinstance(path, bytes):
        return path
    return os.fsencode(path) if os.name != "nt" else path.encode("utf-8")


def _setUserDataDir(userdir):
    """libchewing 0.13 會把「使用者資料目錄」放在搜尋路徑最前面 (找 symbols.dat、
    swkb.dat、詞庫)。沒指定時是 %USERPROFILE%/ChewingTextService 或 %APPDATA%/Chewing，
    也就是另外安裝的新酷音 (windows-chewing-tsf) 的目錄，它的檔案會蓋過 WIME 自己的設定。
    以環境變數 CHEWING_USER_PATH 指到 WIME 的設定目錄 (行程內有效)"""
    if userdir:
        if isinstance(userdir, bytes):
            userdir = userdir.decode("utf-8")
        os.environ["CHEWING_USER_PATH"] = userdir


class ChewingError(RuntimeError):
    """The libchewing context could not be created properly, e.g. the dictionary
    files are missing, or the user phrase dictionary cannot be read (corrupt,
    locked, read-only)."""


class ChewingFault(OSError):
    """A native fault (such as an access violation) inside chewing.dll. ctypes
    turns Windows SEH exceptions into a plain OSError; this subclass lets callers
    tell them apart from ordinary I/O errors."""


def Init(datadir, userdir):
    return _libchewing.chewing_Init(datadir, userdir)


def _guarded(func, ctx):
    def call(*args):
        try:
            return func(ctx, *args)
        except OSError as err:
            raise ChewingFault(*err.args) from err
    return call


class ChewingContext:
    def __init__(self, **kwargs):
        """ChewingContext() 用 libchewing 的預設路徑；ChewingContext(syspath=..., userpath=...)
        指定系統詞庫的搜尋路徑 (; 分隔) 與使用者詞庫檔案 (或 ":memory:")。路徑可以是 str
        或 UTF-8 bytes。userdir 是使用者資料目錄 (預設是 userpath 所在的目錄)。
        詞庫載入失敗時丟出 ChewingError (detectErrors=False 時不檢查)"""
        self.ctx = None  # __del__ runs even if the constructor raises
        self._errors = []
        if not kwargs:
            ctx = _libchewing.chewing_new()
        else:
            syspath = encodePath(kwargs.get("syspath", None))
            userpath = encodePath(kwargs.get("userpath", None))
            userdir = kwargs.get("userdir", None)
            if userdir is None and userpath and userpath != b":memory:":
                userdir = os.path.dirname(userpath.decode("utf-8"))
            _setUserDataDir(userdir)
            # 只在建立 context 時接 log 回呼，用來判斷詞庫有沒有載入成功 (見下方)。之後就
            # 拿掉：libchewing 有接回呼時，每一筆 debug/trace 訊息都會格式化再交給回呼
            # (不論等級)，例如每加一個詞就把整個詞庫印成字串，轉換幾千個詞的舊詞庫要
            # 好幾十秒，每個按鍵也慢上一截。detectErrors=False 完全不接回呼
            logger = None
            if kwargs.get("detectErrors", True):
                self._logger = _LOGGER(self._log)
                logger = cast(self._logger, c_void_p)
            ctx = _libchewing.chewing_new3(syspath, userpath, SYSTEM_DICTIONARIES, logger, None)
            if ctx and logger:
                _libchewing.chewing_set_logger(c_void_p(ctx), None, None)
        if not ctx:
            raise ChewingError("chewing_new3() failed")
        self.ctx = c_void_p(ctx)
        failed = [msg for msg in self._errors if msg.startswith((_USER_DICT_FAILED, _SYSTEM_DICT_FAILED))]
        if failed:
            self.close()
            raise ChewingError(b"; ".join(failed).decode("utf-8", "replace"))

    def _log(self, data, level, fmt, message):
        try:
            if level >= LOG_ERROR and message:
                # "[src/editor/mod.rs:203 chewing::editor] Failed to load user dict: ..."
                text = message.rstrip(b"\n")
                if text.startswith(b"[") and b"] " in text:
                    text = text.split(b"] ", 1)[1]
                if len(self._errors) < 20:
                    self._errors.append(text)
        except Exception:
            pass  # 例外不能丟回 Rust

    def errors(self):
        """libchewing 記錄過的錯誤訊息 (str)"""
        return [msg.decode("utf-8", "replace") for msg in self._errors]

    def close(self):
        """Free the native context now (it also closes the user phrase database).
        If freeing it faults, the context is abandoned instead."""
        ctx, self.ctx = self.ctx, None
        # drop the cached wrappers bound to the old pointer: a later call then passes
        # NULL, which libchewing ignores, instead of a freed context
        for name in [key for key in self.__dict__ if key != "ctx" and not key.startswith("_")]:
            del self.__dict__[name]
        if ctx:
            try:
                _libchewing.chewing_delete(ctx)
            except OSError:
                pass

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass  # interpreter shutdown: the module globals may already be gone

    def __getattr__(self, name):
        if name.startswith("_") or name == "ctx":
            raise AttributeError(name)
        func = 'chewing_' + name
        # force the use of the APIs returning const char* to avoid memory leaks
        if name.endswith("_String"):
            func += "_static"
        if func in _libchewing.__dict__:
            wrap = _guarded(_libchewing.__dict__[func], self.ctx)
            setattr(self, name, wrap)
            return wrap
        elif hasattr(_libchewing, func):
            wrap = _guarded(_libchewing.__getattr__(func), self.ctx)
            setattr(self, name, wrap)
            return wrap
        else:
            raise AttributeError(name)

    # The original libchewing API is set_selKey (without 's')
    # It only accepts an integer array. Let's create a new API that accepts
    # a python string
    def set_selKeys(self, selKeys):
        selKeyCodes = (c_int * len(selKeys))()
        for i, key in enumerate(selKeys):
            selKeyCodes[i] = ord(key)
        try:
            _libchewing.chewing_set_selKey(self.ctx, selKeyCodes, len(selKeys))
        except OSError as err:
            raise ChewingFault(*err.args) from err

    def userPhrases(self):
        """列出使用者詞庫的所有詞：[(詞, 注音)]，注音的音節以空白分隔"""
        phrase_len = c_uint(0)
        bopomofo_len = c_uint(0)
        phrases = []
        try:
            _libchewing.chewing_userphrase_enumerate(self.ctx)
            while _libchewing.chewing_userphrase_has_next(self.ctx, byref(phrase_len), byref(bopomofo_len)) == 1:
                phrase_buf = create_string_buffer(phrase_len.value)
                bopomofo_buf = create_string_buffer(bopomofo_len.value)
                if _libchewing.chewing_userphrase_get(self.ctx, phrase_buf, phrase_len,
                                                      bopomofo_buf, bopomofo_len) != 0:
                    break
                phrases.append((phrase_buf.value.decode("utf-8", "replace"),
                                bopomofo_buf.value.decode("utf-8", "replace")))
        except OSError as err:
            raise ChewingFault(*err.args) from err
        return phrases

    def Configure(self, cpp, maxlen, direction, space, kbtype):
        self.set_candPerPage(cpp)
        self.set_maxChiSymbolLen(maxlen)
        self.set_addPhraseDirection(direction)
        self.set_spaceAsSelection(space)
        self.set_KBType(kbtype)
