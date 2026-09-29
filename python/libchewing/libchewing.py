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
from functools import partial
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
_libchewing.chewing_bopomofo_String_static.restype = c_char_p
_libchewing.chewing_aux_String_static.restype = c_char_p
_libchewing.chewing_kbtype_String_static.restype = c_char_p
# the context is a pointer: the default c_int return type truncates it on 64-bit
_libchewing.chewing_new.restype = c_void_p
_libchewing.chewing_new2.restype = c_void_p


class ChewingError(RuntimeError):
    """chewing_new() / chewing_new2() returned NULL, e.g. the data files are
    missing or the user phrase database is locked, corrupt or read-only."""


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
        self.ctx = None  # __del__ runs even if the constructor raises
        if not kwargs:
            ctx = _libchewing.chewing_new()
        else:
            syspath = kwargs.get("syspath", None)
            userpath = kwargs.get("userpath", None)
            ctx = _libchewing.chewing_new2(
                syspath,
                userpath,
                None,
                None)
        if not ctx:
            raise ChewingError("chewing_new2() failed")
        self.ctx = c_void_p(ctx)

    def close(self):
        """Free the native context now (it also closes the user phrase database).
        If freeing it faults, the context is abandoned instead."""
        ctx, self.ctx = self.ctx, None
        # drop the cached wrappers bound to the old pointer: a later call then passes
        # NULL, which libchewing ignores, instead of a freed context
        for name in [key for key in self.__dict__ if key != "ctx"]:
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
        if name.startswith("__") or name == "ctx":
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

    def Configure(self, cpp, maxlen, direction, space, kbtype):
        self.set_candPerPage(cpp)
        self.set_maxChiSymbolLen(maxlen)
        self.set_addPhraseDirection(direction)
        self.set_spaceAsSelection(space)
        self.set_KBType(kbtype)
