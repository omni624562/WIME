#! python3
# Copyright (C) 2016 Hong Jen Yee (PCMan) <pcman.tw@gmail.com>
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

import json
import os
import io
import time
import shutil

DEF_FONT_SIZE = 12

SWITCH_LANG_WITH_BOTH_SHIFT = 0
SWITCH_LANG_WITH_LEFT_SHIFT = 1
SWITCH_LANG_WITH_RIGHT_SHIFT = 2

selKeys=(
    "1234567890"
)

# Valid ranges for integer settings (at least as wide as the settings page allows);
# anything outside falls back to the default in CinBaseConfig.normalize(). Table
# indices are range-checked against the IME's table list where they are used.
_INT_RANGES = (
    ("candPerRow", 1, 10),
    ("candPerPage", 1, 10),
    ("candidatePerRow", 1, 10),
    ("candMaxItems", 1, 10000),
    ("fontSize", 6, 200),
    ("candidateOpacity", 30, 100),
    ("candidatePositionMode", 0, 1),
    ("candidateMinWidth", 0, 4000),
    ("candidateMaxWidth", 0, 4000),
    ("selWildcardType", 0, 1),
    ("switchLangWithWhichShift", 0, 2),
    ("messageDurationTime", 0, 60),
    ("selCinType", 0, 999),
    ("selRCinType", 0, 999),
    ("selHCinType", 0, 999),
)


def _toInt(value, default):
    """"5" / 5.0 / " 7 " -> int; "", None, "abc", lists... -> default."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return value if isinstance(value, int) else default


def _toBool(value, default):
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off", ""):
            return False
    return default

class CinBaseConfig:

    def __init__(self):
        self.candPerRow = 3
        self.defaultEnglish = False
        self.defaultFullSpace = False
        self.disableOnStartup = False
        self.switchLangWithShift = True
        self.switchLangWithWhichShift = SWITCH_LANG_WITH_BOTH_SHIFT
        self.outputSmallLetterWithShift = False
        self.switchPageWithSpace = False
        self.messageDurationTime = 3
        self.hidePromptMessages = True
        self.playSoundWhenNonCand = False
        self.directShowCand = False
        self.autoCommitSingleCandidate = False
        self.directCommitSymbol = False
        self.fontSize = DEF_FONT_SIZE
        self.selCinType = 0
        self.ignorePrivateUseArea = True
        self.selKeyType = 0
        self.candPerPage = 9
        self.cursorCandList = True
        self.fullShapeSymbols = False
        self.directOutFSymbols = False
        self.directOutMSymbols = True
        self.easySymbolsWithShift = False
        self.showPhrase = False
        self.sortByPhrase = True
        self.supportWildcard = True
        self.compositionBufferMode = False
        self.autoMoveCursorInBrackets = False
        self.selWildcardType = 0
        self.imeReverseLookup = False
        self.homophoneQuery = False
        self.selHCinType = 0
        self.userExtendTable = False
        self.reLoadTable = False
        self.priorityExtendTable = False
        self.selRCinType = 0
        self.candMaxItems = 100
        self.messageDurationTime = 3
        self.keyboardType = 0
        self.selDayiSymbolCharType = 0
        self.intelligentSelect = True
        self.intelligentSelectRecent = True
        self.intelligentSelectContext = True
        self.hideComposition = False
        self.hideCompositionLabel = ""
        self.imeDisplayName = ""
        self.candidateModernStyle = False
        self.candidateLayout = "horizontal"
        self.candidatePerRow = 6
        self.candidateEdgeAvoidance = True
        self.candidatePositionMode = 0 # 0 = 跟隨游標，1 = 螢幕下緣置中
        self.candidateOpacity = 100 # 候選窗不透明度 30~100（百分比）
        self.candidateTheme = "System"  # 跟隨 Windows 深淺色，backend 送出前解析成實際主題
        self.candidateKeyStyle = "keycap"
        self.candidateHeaderStyle = "badge"
        self.candidateMessageStyle = "badge"
        self.candidateMessageBehavior = "progressive"
        self.candidateStableWidth = False
        self.candidateMinWidth = 0
        self.candidateWrapToMaxWidth = True
        self.candidateMaxWidth = 300
        self.candidateColors = {}
        self.candidateStyle = {
            "contentMargin": 6,
            "textMargin": 4,
            "borderRadius": 6,
        }

        self.ignoreSaveList = ["ignoreSaveList", "curdir", "cinFileList", "selCinFile", "imeDirName", "_version", "_lastUpdateTime"]
        self.curdir = os.path.abspath(os.path.dirname(__file__))
        self.cinFileList = []
        self.selCinFile = ""
        self.imeDirName = ""

        # version: last modified time of (config.json, symbols.dat, swkb.dat, fsymbols.dat, flangs.dat, userphrase.dat, excludephrase.dat)
        self._version = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self._lastUpdateTime = 0.0

    def getConfigDir(self):
        config_dir = os.path.join(os.path.expandvars("%APPDATA%"), "PIME", self.imeDirName)
        os.makedirs(config_dir, mode=0o700, exist_ok=True)
        return config_dir

    def getConfigFile(self, name="config.json"):
        return os.path.join(self.getConfigDir(), name)

    def getSelKeys(self):
        return selKeys[self.selKeyType]

    def getLastTime(self):
        return self._lastTime

    def load(self):
        # Layer 1: apply shipped defaults so new keys reach all users regardless of
        # whether they already have an APPDATA config from a previous install.
        # The shipped files are UTF-8 with Chinese text; the backend runs without
        # Python's UTF-8 mode, so open() without an encoding used the ANSI code page
        # (cp950 on zh-TW Windows), failed, and the error was swallowed - none of the
        # per-IME defaults (directShowCand, the * wildcard, modern layout, display
        # name...) ever took effect for zh-TW users.
        default_config = os.path.join(self.getDefaultConfigDir(), "config.json")
        try:
            if os.path.exists(default_config) and os.stat(default_config).st_size > 0:
                with open(default_config, "r", encoding="utf-8-sig") as f:
                    self.__dict__.update(json.load(f))
        except Exception:
            pass
        self.normalize()
        shipped = dict(self.__dict__)

        # Layer 2: overlay with the user's personal config (APPDATA or legacy home-dir path).
        filename = self.getConfigFile()
        try:
            if not os.path.exists(filename) or os.stat(filename).st_size == 0:
                filename = os.path.join(os.path.expanduser("~"), "PIME", self.imeDirName, "config.json")

                if not os.path.exists(filename) or os.stat(filename).st_size == 0:
                    filename = None
                else:
                    src_dir = os.path.join(os.path.expanduser("~"), "PIME", self.imeDirName)
                    dst_dir = self.getConfigDir()
                    self.copytree(src_dir, dst_dir)
                    filename = self.getConfigFile()

            if filename:
                self.__dict__.update(self._readUserConfig(filename))
        except Exception:
            # Keep the user's file: it used to be overwritten with defaults here, so a
            # typo (or the encoding bug above) silently wiped all of their settings.
            # Keep a copy aside for them and carry on with the defaults.
            self._backupBrokenConfig(filename)
        self.normalize(shipped)
        self.update()

    @staticmethod
    def _readUserConfig(filename):
        # Written as ASCII JSON by the backend and the settings page; tolerate a BOM
        # and legacy files hand-edited in the ANSI code page.
        with open(filename, "rb") as f:
            raw = f.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("mbcs")
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("config.json is not a JSON object")
        return data

    @staticmethod
    def _backupBrokenConfig(filename):
        try:
            if filename and os.path.exists(filename):
                backup = "%s.broken-%d" % (filename, int(os.path.getmtime(filename)))
                if not os.path.exists(backup):
                    shutil.copy2(filename, backup)
        except Exception:
            pass

    def normalize(self, fallback=None):
        """Coerce settings read from config.json to the types and ranges the code
        expects. Values come from the settings page (older/newer versions, empty
        number fields are saved as ""), or from hand edits; a wrong type used to raise
        on activation or on every keystroke (e.g. candidatePerRow "" -> TypeError in
        the pager, selWildcardType 2 -> selWildcardChar never set).
        Invalid values are replaced from fallback (the shipped per-IME defaults when
        normalizing the user's layer), else from the class defaults."""
        defaults = type(self)().__dict__
        if fallback is None:
            fallback = defaults
        for key, default in defaults.items():
            if key.startswith("_") or key in self.ignoreSaveList:
                continue
            value = self.__dict__.get(key, default)
            good = fallback.get(key, default)
            if isinstance(default, bool):
                if not isinstance(value, bool):
                    self.__dict__[key] = _toBool(value, good)
            elif isinstance(default, int):
                if isinstance(value, bool) or not isinstance(value, int):
                    self.__dict__[key] = _toInt(value, good)
            elif isinstance(default, str):
                # 設定頁把看起來像數字的文字欄位存成數字（顯示名稱填 "123" 就變 123）
                if not isinstance(value, str):
                    self.__dict__[key] = str(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else good
            elif isinstance(default, dict):
                if not isinstance(value, dict):
                    self.__dict__[key] = good
        for key, low, high in _INT_RANGES:
            if not low <= self.__dict__[key] <= high:
                good = fallback.get(key, defaults[key])
                self.__dict__[key] = good if low <= good <= high else defaults[key]

    def toJson(self):
        return {key: value for key, value in self.__dict__.items() if not key.startswith("_") and not key in self.ignoreSaveList}

    def save(self):
        filename = self.getConfigFile()
        tmp_filename = filename + ".tmp"
        try:
            # write-then-rename: a crash or full disk mid-write must not leave a
            # truncated config.json (which the next load would treat as broken)
            with open(tmp_filename, "w", encoding="utf-8") as f:
                json.dump(self.toJson(), f, sort_keys=True, indent=4)
            os.replace(tmp_filename, filename)
            self.update()
        except Exception:
            try:
                if os.path.exists(tmp_filename):
                    os.remove(tmp_filename)
            except Exception:
                pass

    def getDataDir(self):
        return os.path.join(os.path.dirname(__file__), "data")

    def getCinDir(self):
        return os.path.join(os.path.dirname(__file__), "cin")

    def getJsonDir(self):
        return os.path.join(os.path.dirname(__file__), "json")

    def getDefaultConfigDir(self):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, "input_methods", self.imeDirName, "config"))

    def findFile(self, dirs, name):
        for dirname in dirs:
            path = os.path.join(dirname, name)
            if os.path.exists(path):
                return path
        return None

    def copytree(self, src, dst, symlinks=False, ignore=None):
        for item in os.listdir(src):
            s = os.path.join(src, item)
            d = os.path.join(dst, item)
            if os.path.isdir(s):
                shutil.copytree(s, d, symlinks, ignore)
            else:
                shutil.copy2(s, d)

    # check if the config files are changed and relaod as needed
    def update(self):
        # avoid checking mtime of files too frequently
        if (time.time() - self._lastUpdateTime) < 3.0:
            return

        try:
            configTime = os.path.getmtime(self.getConfigFile())
        except Exception:
            configTime = 0.0

        datadirs = (self.getConfigDir(), self.getDataDir())
        symbolsTime = 0.0
        symbolsFile = self.findFile(datadirs, "symbols.dat")
        if symbolsFile:
            try:
                symbolsTime = os.path.getmtime(symbolsFile)
            except Exception:
                pass

        ezSymbolsTime = 0.0
        ezSymbolsFile = self.findFile(datadirs, "swkb.dat")
        if ezSymbolsFile:
            try:
                ezSymbolsTime = os.path.getmtime(ezSymbolsFile)
            except Exception:
                pass

        fsymbolsTime = 0.0
        fsymbolsFile = self.findFile(datadirs, "fsymbols.dat")
        if fsymbolsFile:
            try:
                fsymbolsTime = os.path.getmtime(fsymbolsFile)
            except Exception:
                pass

        flangsTime = 0.0
        flangsFile = self.findFile(datadirs, "flangs.dat")
        if flangsFile:
            try:
                flangsTime = os.path.getmtime(flangsFile)
            except Exception:
                pass

        userphraseTime = 0.0
        userphraseFile = self.findFile(datadirs, "userphrase.dat")
        if userphraseFile:
            try:
                userphraseTime = os.path.getmtime(userphraseFile)
            except Exception:
                pass

        extendtableTime = 0.0
        extendtableFile = self.findFile(datadirs, "extendtable.dat")
        if extendtableFile:
            try:
                extendtableTime = os.path.getmtime(extendtableFile)
            except Exception:
                pass

        excludephraseTime = 0.0
        excludephraseFile = self.findFile(datadirs, "excludephrase.dat")
        if excludephraseFile:
            try:
                excludephraseTime = os.path.getmtime(excludephraseFile)
            except Exception:
                pass

        lastConfigTime = self._version[0]
        self._version = (configTime, symbolsTime, ezSymbolsTime, fsymbolsTime, flangsTime, userphraseTime, excludephraseTime)

        # the main config file is changed, reload it
        if lastConfigTime != configTime:
            if not hasattr(self, "_in_update"): # avoid recursion
                self._in_update = True  # avoid recursion since update() will be called by load
                self.load()
                del self._in_update

        self._lastUpdateTime = time.time()

    def getVersion(self):
        return self._version

    def isConfigChanged(self, currentVersion):
        return currentVersion[0] != self._version[0]

    # isFullReloadNeeded() checks whether you need to delete the
    # existing chewing context and create a new one.
    # This is often caused by change of data files, such as
    # symbols.dat and swkb.dat files.
    def isFullReloadNeeded(self, currentVersion):
        return currentVersion[1:] != self._version[1:]


# globally shared config object
# load configurations from a user-specific config file
CinBaseConfig = CinBaseConfig()
