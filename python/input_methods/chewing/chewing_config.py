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

import copy
import json
import os
import sys
import time
import shutil

DEF_FONT_SIZE = 16

SWITCH_LANG_WITH_BOTH_SHIFT = 0
SWITCH_LANG_WITH_LEFT_SHIFT = 1
SWITCH_LANG_WITH_RIGHT_SHIFT = 2

# from libchewing/include/internal/userphrase-private.h
DB_NAME = "chewing.sqlite3"

selKeys = (
    "1234567890",
    "asdfghjkl;",
    "asdfzxcv89",
    "asdfjkl789",
    "aoeuhtn789",
    "1234qweras"
)

# 整數設定的合法範圍（至少和設定頁允許的一樣寬）。這些值會直接傳給 libchewing (ctypes)
# 或拿來當索引：以前設定頁清空的欄位 (null)、手動改成的小數或超大數字，會讓啟用輸入法
# 或每個按鍵都丟例外。型別不對或超出範圍的值改用預設值
_INT_RANGES = {
    "candPerPage": (1, 10),
    "keyboardLayout": (0, 12),  # 設定頁的 13 種鍵盤排列
    "leftRightAction": (0, 1),
    "upDownAction": (0, 1),
    "selKeyType": (0, len(selKeys) - 1),
    "shiftMoveCursor": (0, 1),
    "spaceKeyAction": (0, 1),
    "spaceKeyCandidatesAction": (0, 1),
    "switchLangWithWhichShift": (0, 2),
    "fontSize": (6, 200),
    "candidatePerRow": (1, 10),
    "candidatePositionMode": (0, 1),
    "candidateOpacity": (30, 100),
    "candidateMinWidth": (0, 4000),
    "candidateMaxWidth": (0, 4000),
}
_C_INT_RANGE = (-2 ** 31, 2 ** 31 - 1)

# 以前出貨的候選窗最大寬度，太窄：新酷音預設 16pt，100% 縮放時一列 6 個單字候選要
# 336px（keycap 選字鍵，後端預設：6×49 + 5×6 + 2×6）或 318px（word-first，設定頁
# 儲存時寫入的），300 讓一頁 9 個排成 5＋4。預設改成 340，keycap 在 125%、150% 也
# 放得下（大易/酷倉是 12pt，用 320 就夠；tests/test_candidate_width.py 依
# CandidateWindow 的算法與實際字寬檢查）。使用者的 config.json 都留著舊預設 300
# （第一次載入與設定頁儲存時整份寫出），載入時剛好是 300 就換成新預設。設定工具
# 顯示的值也經過 normalizeValues，兩邊一致
LEGACY_CANDIDATE_MAX_WIDTH = 300

# 已移除的設定。舊的 config.json 還帶著它們，載入（含設定工具讀檔）時丟掉，
# 設定頁儲存時就不會再寫回去
#   candPerRow: 舊版候選窗「每列顯示候選字個數」。舊版候選窗移除後沒有任何作用，
#     每列幾個候選由 candidatePerRow（候選窗外觀的「每列候選字數」）決定
_RETIRED_KEYS = ("candPerRow",)


def _toInt(value):
    """5 / True / 5.0 / " 7 " -> int；None、""、"abc"、list… -> None"""
    if isinstance(value, int):  # bool 也是 int (設定頁的核取方塊)
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _toBool(value):
    if isinstance(value, int):  # 設定頁的下拉選單存成 0/1，保留原樣
        return value
    if isinstance(value, float):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off", ""):
            return False
    return None


def normalizeValues(values, defaults):
    """回傳 values 的副本：已知設定的值轉成程式預期的型別與範圍，無效的值改用
    defaults 裡的預設值，舊的出貨預設值（LEGACY_CANDIDATE_MAX_WIDTH）換成新的，
    已移除的設定（_RETIRED_KEYS）丟掉；其他不認得的鍵原樣保留。"""
    result = {key: value for key, value in values.items() if key not in _RETIRED_KEYS}
    for key, default in defaults.items():
        if key not in result:
            continue
        value = result[key]
        if isinstance(default, bool):
            value = _toBool(value)
        elif isinstance(default, int):
            value = _toInt(value)
            low, high = _INT_RANGES.get(key, _C_INT_RANGE)
            if value is not None and not low <= value <= high:
                value = None
        elif isinstance(default, str):
            if not isinstance(value, str):
                value = None
        elif isinstance(default, dict):
            if not isinstance(value, dict):
                value = None
            elif key == "candidateStyle":
                # C++ 以整數讀取這些欄位，其他型別會讓整個回覆被丟掉
                value = {k: v for k, v in value.items()
                         if isinstance(v, int) and not isinstance(v, bool)}
        if value is None:
            value = copy.deepcopy(default)
        result[key] = value
    if result.get("candidateMaxWidth") == LEGACY_CANDIDATE_MAX_WIDTH and "candidateMaxWidth" in defaults:
        result["candidateMaxWidth"] = defaults["candidateMaxWidth"]
    return result


_defaultValues = None


def defaultValues():
    """出廠預設值 (不讀使用者的設定檔)"""
    global _defaultValues
    if _defaultValues is None:
        _defaultValues = ChewingConfig(load=False).toJson()
    return copy.deepcopy(_defaultValues)


def readUserConfig(filename):
    """讀取 config.json；容許 BOM (記事本「UTF-8 含 BOM」、PowerShell 5) 與以 ANSI
    字碼頁手動存檔的舊檔。內容不是 JSON 物件時丟出 ValueError。"""
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


def _hasContent(filename):
    try:
        return os.stat(filename).st_size > 0
    except OSError:
        return False


class ChewingConfig:

    def __init__(self, load=True):
        self.addPhraseForward = True
        self.advanceAfterSelection = True
        self.autoLearn = True
        self.candPerPage = 9
        self.defaultEnglish = False
        self.defaultFullSpace = False
        self.disableOnStartup = False
        self.easySymbolsWithCtrl = False
        self.easySymbolsWithShift = True
        self.enableCapsLock = True
        self.enableShiftSpace = True
        self.escCleanAllBuf = True
        self.fontSize = DEF_FONT_SIZE
        self.fullShapeSymbols = True
        self.fullShapeSymbolsWithShift = True
        self.keyboardLayout = 0
        self.leftRightAction = 0
        self.phraseChoiceRearward = False
        self.selKeyType = 0
        self.shiftMoveCursor = 0
        self.spaceKeyAction = 1
        self.spaceKeyCandidatesAction = 0
        self.switchLangWithShift = True
        self.switchLangWithWhichShift = SWITCH_LANG_WITH_BOTH_SHIFT
        self.upDownAction = 0
        self.upperCaseWithShift = True
        self.candidateLayout = "horizontal"
        self.candidatePerRow = 6
        self.candidateEdgeAvoidance = True
        self.candidatePositionMode = 0 # 0 = 跟隨游標，1 = 螢幕下緣置中
        self.candidateOpacity = 100 # 候選窗不透明度 30~100（百分比）
        self.candidateTheme = "System"  # 跟隨 Windows 深淺色，backend 送出前解析成實際主題
        self.candidateKeyStyle = "keycap"
        self.candidateMessageStyle = "badge"
        self.candidateMessageBehavior = "progressive"
        self.candidateStableWidth = True
        self.candidateMinWidth = 286
        self.candidateWrapToMaxWidth = True
        self.candidateMaxWidth = 340  # 16pt 一列 6 個單字要 336px（見 LEGACY_CANDIDATE_MAX_WIDTH）
        self.candidateColors = {}
        self.candidateStyle = {
            "contentMargin": 6,
            "textMargin": 4,
            "borderRadius": 6,
        }

        # version: last modified time of (config.json, symbols.dat, swkb.dat)
        self._version = (0.0, 0.0, 0.0)
        self._lastUpdateTime = None  # time.monotonic() of the last update()
        if load:
            self.load()  # try to load from the config file

    def getConfigDir(self):
        config_dir = os.path.join(
            os.path.expandvars("%APPDATA%"), "PIME", "chewing")
        os.makedirs(config_dir, mode=0o700, exist_ok=True)
        return config_dir

    def getConfigFile(self, name="config.json"):
        return os.path.join(self.getConfigDir(), name)

    def getUserPhrase(self):
        return os.path.join(self.getConfigDir(), DB_NAME)

    def getSelKeys(self):
        return selKeys[self.selKeyType]

    def getLastTime(self):
        return self._lastUpdateTime

    def load(self):
        filename = self.getConfigFile()
        if not _hasContent(filename):
            self.migrateLegacyConfig()
        version = self._currentVersion()  # 讀檔前先記下版本，讀檔期間的變更下次還會重讀
        if _hasContent(filename):
            try:
                values = readUserConfig(filename)
            except Exception as err:
                # 不能覆寫使用者的檔案：以前多一個逗號、存成含 BOM 的 UTF-8，所有設定就被
                # 預設值 (或記憶體中的舊值) 蓋掉。另存一份，沿用目前的設定 (啟動時是預設值)
                print("chewing: cannot read %s: %s" % (filename, err), file=sys.stderr)
                self._backupBrokenConfig(filename)
            else:
                self._applyValues(values)
        else:
            self.save()  # 還沒有設定檔：寫出預設值
            version = self._currentVersion()
        self._version = version
        self._lastUpdateTime = time.monotonic()

    def _applyValues(self, values):
        # 只接受已知的公開設定：以前 "update"、"getSelKeys" 之類的鍵會蓋掉方法，
        # "_lastUpdateTime" 之類的內部欄位會讓設定再也不會重新載入
        defaults = defaultValues()
        known = {key: value for key, value in values.items() if key in defaults}
        self.__dict__.update(normalizeValues(known, defaults))

    @staticmethod
    def _backupBrokenConfig(filename):
        try:
            backup = "%s.broken-%d" % (filename, int(os.path.getmtime(filename)))
            if not os.path.exists(backup):
                shutil.copy2(filename, backup)
        except Exception:
            pass

    def migrateLegacyConfig(self):
        # 舊版 PIME 把設定放在 %USERPROFILE%\PIME\chewing。只在新位置還沒有設定檔與詞庫時
        # 搬一次，而且不覆寫任何檔案：以前使用者刪掉 config.json 想重設設定，整個舊目錄
        # 就會被複製過來，連目前學到的詞庫 (chewing.sqlite3) 都被舊檔取代
        src_dir = os.path.join(os.path.expanduser("~"), "PIME", "chewing")
        dst_dir = self.getConfigDir()
        if os.path.normcase(os.path.abspath(src_dir)) == os.path.normcase(os.path.abspath(dst_dir)):
            return
        if not _hasContent(os.path.join(src_dir, "config.json")) or os.path.exists(self.getUserPhrase()):
            return
        try:
            self.copytree(src_dir, dst_dir)
        except Exception as err:
            print("chewing: cannot migrate %s: %s" % (src_dir, err), file=sys.stderr)

    def toJson(self):
        return {key: value for key, value in self.__dict__.items() if not key.startswith("_")}

    def save(self):
        filename = self.getConfigFile()
        tmp_filename = filename + ".tmp"
        try:
            with open(tmp_filename, "w", encoding="UTF-8") as f:
                json.dump(self.toJson(), f, ensure_ascii=False, indent=4)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())  # 斷電後才不會留下 0 位元組的 config.json
            os.replace(tmp_filename, filename)
            return True
        except Exception as err:
            print("chewing: cannot save %s: %s" % (filename, err), file=sys.stderr)
            try:
                if os.path.exists(tmp_filename):
                    os.remove(tmp_filename)
            except Exception:
                pass
            return False

    def getDataDir(self):
        return os.path.join(os.path.dirname(__file__), "data")

    def findFile(self, dirs, name):
        for dirname in dirs:
            path = os.path.join(dirname, name)
            if os.path.exists(path):
                return path
        return None

    def copytree(self, src, dst, symlinks=False, ignore=None):
        # 目的地已有的檔案一律保留
        for item in os.listdir(src):
            s = os.path.join(src, item)
            d = os.path.join(dst, item)
            if os.path.exists(d):
                continue
            if os.path.isdir(s):
                shutil.copytree(s, d, symlinks, ignore)
            else:
                shutil.copy2(s, d)

    def _currentVersion(self):
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
        return (configTime, symbolsTime, ezSymbolsTime)

    # check if the config files are changed and relaod as needed
    def update(self):
        # avoid checking mtime of files too frequently. monotonic: after the wall
        # clock was set back (NTP), time.time() stayed "recent" and reloads stopped
        now = time.monotonic()
        if self._lastUpdateTime is not None and (now - self._lastUpdateTime) < 3.0:
            return
        self._lastUpdateTime = now

        version = self._currentVersion()
        configChanged = version[0] != self._version[0]
        self._version = version
        # the main config file is changed, reload it
        if configChanged:
            self.load()

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
chewingConfig = ChewingConfig()
