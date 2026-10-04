#! python3
# Copyright (C) 2015 - 2016 Hong Jen Yee (PCMan) <pcman.tw@gmail.com>
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

from keycodes import *  # for VK_XXX constants
from textService import *
import os.path
import time
from libchewing import ChewingContext, ChewingError, ChewingFault, CHEWING_DATA_DIR, \
    CHINESE_MODE, ENGLISH_MODE, FULLSHAPE_MODE, HALFSHAPE_MODE, encodeDataPath

import sys
import copy
from ctypes import windll  # for ShellExecuteW() and GetAsyncKeyState()

from .chewing_config import chewingConfig, SWITCH_LANG_WITH_BOTH_SHIFT, SWITCH_LANG_WITH_LEFT_SHIFT, SWITCH_LANG_WITH_RIGHT_SHIFT
import sqlite3


# 按鍵內碼和名稱的對應
keyNames = {
    VK_ESCAPE: "Esc",
    VK_RETURN: "Enter",
    VK_TAB: "Tab",
    VK_DELETE: "Del",
    VK_BACK: "Backspace",
    VK_UP: "Up",
    VK_DOWN: "Down",
    VK_LEFT: "Left",
    VK_RIGHT: "Right",
    VK_HOME: "Home",
    VK_END: "End",
    VK_PRIOR: "PageUp",
    VK_NEXT: "PageDown"
}

# shift + space 熱鍵的 GUID
SHIFT_SPACE_GUID = "{f1dae0fb-8091-44a7-8a0c-3082a1515447}"

# 選單項目和語言列按鈕的 command ID
ID_SWITCH_LANG = 1
ID_SWITCH_SHAPE = 2
ID_SETTINGS = 3
ID_MODE_ICON = 4
ID_ABOUT = 5
ID_WEBSITE = 6
ID_GROUP = 7
ID_BUGREPORT = 8
ID_DICT_BUGREPORT = 9
ID_CHEWING_HELP = 10
ID_HASHED = 11
ID_MOEDICT = 13
ID_DICT = 14
ID_SIMPDICT = 15
ID_LITTLEDICT = 16
ID_PROVERBDICT = 17
ID_OUTPUT_SIMP_CHINESE = 18
ID_USER_PHRASE_EDITOR = 19

# 候選窗主題共用邏輯已抽出到頂層 candidate_theme 模組（重構 B）。
from candidate_theme import (
    LEGACY_LIGHT_CANDIDATE_COLORS,
    systemPrefersLightTheme,
    resolveCandidateTheme,
    candidateColorsForTheme,
)


def isBopomofoChar(ch):
    code = ord(ch)
    return (
        0x3100 <= code <= 0x312F or
        0x31A0 <= code <= 0x31BF or
        ch in "˙ˊˇˋ"
    )


def splitTrailingBopomofo(text):
    rootStart = len(text)
    while rootStart > 0 and isBopomofoChar(text[rootStart - 1]):
        rootStart -= 1
    return text[:rootStart], text[rootStart:]


# libchewing 回傳的是 UTF-8 bytes。資料檔有問題時可能不是合法的 UTF-8 (symbols.dat 一行
# 超過 511 bytes 會被 libchewing 截斷在字的中間、或檔案存成 ANSI)，以前嚴格解碼會讓之後
# 每個按鍵都丟例外，連 Esc 都清不掉
def decodeText(data):
    return data.decode("UTF-8", "replace") if data else ""


# 無法開啟使用者詞庫時只提示一次 (每次切換視窗都會重新啟用輸入法)
_userPhraseWarningShown = False


# from libchewing/include/global.h
AUTOLEARN_ENABLED = 0
AUTOLEARN_DISABLED = 1

# libchewing 編輯區的上限 (MAX_CHI_SYMBOL_LEN)，超過的值會被忽略
MAX_CHI_SYMBOL_LEN = 39

# 掃描碼：分辨放開的是左邊還是右邊的 Shift
LEFT_SHIFT_SCAN_CODE = 0x2A
RIGHT_SHIFT_SCAN_CODE = 0x36


class ChewingTextService(TextService):
    def __init__(self, client):
        TextService.__init__(self, client)
        self.curdir = os.path.abspath(os.path.dirname(__file__))
        self.icon_dir = os.path.join(self.curdir, "icons")
        self.chewingContext = None  # libchewing context

        self.langMode = -1
        self.shapeMode = -1

        # remember last state when the input method is temporarily closed
        self.lastLangMode = None
        self.lastShapeMode = None

        self.lastKeyDownTime = 0.0
        self.lastKeyEvent = None

        self.configVersion = chewingConfig.getVersion()

        # has language buttons
        self.hasLangButtons = False
        self.updateSwitchLangIcon = False  # 更新 中/英 切換 icon

        # 無法開啟使用者詞庫，暫時改用記憶體中的詞庫 (學到的詞不會存檔)
        self.userPhraseFallback = False

        # 切換中英文後畫面上的組字還沒更新 (見 toggleLanguageMode)
        self.compositionSyncPending = False

    def handleRequest(self, msg):
        try:
            return TextService.handleRequest(self, msg)
        except ChewingFault as err:
            # 內附的舊版 chewing.dll 在少數按鍵序列會存取違規 (例如許氏鍵盤的
            # 「k 空白 4 k 空白」)。以前例外一路丟到 server.py，C++ 端會重設整條連線，
            # 之後每個空白鍵、Enter 都再出錯一次。丟掉壞掉的 context、重建一個新的，
            # 並清掉組字狀態 (這個按鍵和正在組的字會遺失)
            return self.recoverFromEngineFault(msg, err)

    def recoverFromEngineFault(self, msg, err):
        print("chewing: chewing.dll fault in %s: %s" % (msg.get("method"), err), file=sys.stderr)
        self.currentReply = {}
        self.closeChewingContext()
        if self.isActivated and self.keyboardOpen:
            self.rememberModes()
            self.initChewingContext()
        self.clearCompositionState()
        if msg.get("method") not in ("onKeyDown", "onKeyUp"):
            # 這個回覆沒有 edit session，畫面上的組字等下一個按鍵再清掉
            self.compositionSyncPending = True
        self.showMessage("新酷音引擎發生錯誤，已自動重新啟動", 3)
        reply = self.currentReply
        self.currentReply = {}
        if msg.get("method") in ("filterKeyDown", "onKeyDown"):
            reply["return"] = True  # 這個按鍵已經處理過了 (丟棄)，不要再送給應用程式
        elif msg.get("method") in ("filterKeyUp", "onKeyUp", "onPreservedKey"):
            reply["return"] = False
        reply["success"] = True
        reply["seqNum"] = msg.get("seqNum", 0)
        return reply

    # 檢查設定檔是否有被更改，是否需要套用新設定
    def checkConfigChange(self):
        cfg = chewingConfig
        cfg.update()  # 更新設定檔狀態
        if not self.chewingContext:
            return  # 鍵盤關閉中；重新開啟時會建立新的 context 並套用設定

        # 比較我們先前存的版本號碼，和目前設定檔的版本號
        if cfg.isFullReloadNeeded(self.configVersion):
            # 資料改變需整個 reload，重建一個新的 chewing context。
            # 組字中先不重建 (會丟掉正在組的字)，等組字結束後的下一個請求再做
            if not self.isComposing():
                self.rebuildChewingContext()
        elif cfg.isConfigChanged(self.configVersion):
            # 只有偵測到設定檔變更，需要套用新設定
            self.applyConfig()

    # 重建 chewing context 時保留目前的中/英、全/半形模式 (以前每次儲存特殊符號設定，
    # 所有程式都被切回預設模式，圖示卻沒更新)
    def rememberModes(self):
        if self.langMode in (CHINESE_MODE, ENGLISH_MODE):
            self.lastLangMode = self.langMode
        if self.shapeMode in (FULLSHAPE_MODE, HALFSHAPE_MODE):
            self.lastShapeMode = self.shapeMode

    def rebuildChewingContext(self):
        self.rememberModes()
        self.closeChewingContext()
        self.clearCompositionState()
        self.initChewingContext()

    # 清掉 Python 端的組字與選字狀態 (新的 context 裡什麼都沒有)
    def clearCompositionState(self):
        self.compositionSyncPending = False
        if self.showCandidates or self.candidateList:
            self.setCandidateList([])
            self.setCandidateCursor(0)
            self.setShowCandidates(False)
        if self.compositionString:
            self.setCompositionString("")
            self.setCompositionCursor(0)

    def customizeCandidateUI(self, force=False):
        cfg = chewingConfig
        uiCandPerRow = self.candidatesPerUiRow()
        ui_args = {
            "candFontName": 'Microsoft JhengHei',
            "candFontSize": cfg.fontSize,
            "candPerRow": uiCandPerRow,
            "candUseCursor": not(cfg.leftRightAction and cfg.upDownAction),
            "candidateLayout": getattr(cfg, 'candidateLayout', 'horizontal'),
            "candidatePerRow": getattr(cfg, 'candidatePerRow', 6),
            "candidateEdgeAvoidance": getattr(cfg, 'candidateEdgeAvoidance', True),
            "candidatePositionMode": getattr(cfg, 'candidatePositionMode', 0),
            "candidateOpacity": getattr(cfg, 'candidateOpacity', 100),
            "candidateTheme": resolveCandidateTheme(cfg),
            "candidateKeyStyle": getattr(cfg, 'candidateKeyStyle', 'keycap'),
            "candidateMessageStyle": getattr(cfg, 'candidateMessageStyle', 'badge'),
            "candidateColors": candidateColorsForTheme(cfg),
            "candidateStyle": getattr(cfg, 'candidateStyle', {}),
            "candidateStableWidth": getattr(cfg, 'candidateStableWidth', False),
            "candidateMinWidth": getattr(cfg, 'candidateMinWidth', 0),
            "candidateWrapToMaxWidth": getattr(cfg, 'candidateWrapToMaxWidth', True),
            "candidateMaxWidth": getattr(cfg, 'candidateMaxWidth', 340),
        }
        if not force and getattr(self, '_lastCandidateUIArgs', None) == ui_args:
            return
        self._lastCandidateUIArgs = copy.deepcopy(ui_args)
        self.customizeUI(**ui_args)

    def updateCandidateHeader(self, rootStr="", forceWindow=False):
        self.currentReply["candidateHeader"] = "新酷音" + (" " + rootStr if rootStr else "")

        totalPage = 0
        currentPage = 0
        try:
            totalPage = self.chewingContext.cand_TotalPage()
            currentPage = self.chewingContext.cand_CurrentPage()
        except Exception:
            pass
        self.currentReply["candidatePageInfo"] = f"{currentPage + 1}/{totalPage}" if totalPage > 0 else ""

        if forceWindow:
            if "candidateList" not in self.currentReply:
                self.setCandidateList(self.candidateList if self.showCandidates and self.candidateList else [])
            self.setShowCandidates(True)

    def applyConfig(self):
        cfg = chewingConfig  # globally shared config object
        chewingContext = self.chewingContext
        if not chewingContext:
            return  # 鍵盤關閉中 (以前會在 None 上呼叫而丟例外)；重新開啟時會再套用
        self.configVersion = cfg.getVersion()

        # 按下 Ctrl+ 數字加入游標前方/後方的詞
        chewingContext.set_addPhraseDirection(cfg.addPhraseForward)

        # 選字後自動把游標往後移一個字
        chewingContext.set_autoShiftCur(cfg.advanceAfterSelection)

        # 每頁顯示幾個候選字
        chewingContext.set_candPerPage(cfg.candPerPage)

        # 按下 ESC 鍵清除正在編輯的字
        chewingContext.set_escCleanAllBuf(cfg.escCleanAllBuf)

        # 鍵盤 layout 種類
        chewingContext.set_KBType(cfg.keyboardLayout)

        # Space 鍵行為
        chewingContext.set_spaceAsSelection(cfg.spaceKeyAction)

        # 設定 UI 外觀
        self.customizeCandidateUI(force=True)

        # 設定是否啟用自動學習功能
        self.setAutoLearn(cfg.autoLearn)

        # 設定選字按鍵 (123456..., asdf.... 等)
        self.setSelKeys(cfg.getSelKeys())

        # 設定向後詞彙選字模式
        chewingContext.set_phraseChoiceRearward(cfg.phraseChoiceRearward)

    # 建立 libchewing context；失敗時傳回 None
    def createChewingContext(self):
        global _userPhraseWarningShown
        cfg = chewingConfig  # 所有 ChewingTextService 共享一份設定物件
        # syspath 參數可包含多個路徑，用 ; 分隔
        # 此處把 user 設定檔目錄插入到 system-wide 資料檔路徑前
        # 如此使用者變更設定後，可以比系統預設值有優先權
        search_paths = b";".join(
            path for path in (encodeDataPath(cfg.getConfigDir()), encodeDataPath(CHEWING_DATA_DIR)) if path)
        # 使用者詞庫由 sqlite 開啟，路徑用 UTF-8
        user_phrase = cfg.getUserPhrase().encode("UTF-8")

        self.userPhraseFallback = False
        try:
            return ChewingContext(syspath=search_paths, userpath=user_phrase)
        except ChewingError:
            # 詞庫被其他程式鎖住、損毀或唯讀時 libchewing 會失敗。以前沒有檢查，
            # 所有按鍵都被吃掉卻打不出字
            print("chewing: cannot open the user phrase database %s" % cfg.getUserPhrase(), file=sys.stderr)
        try:
            chewingContext = ChewingContext(syspath=search_paths, userpath=b":memory:")
        except ChewingError:
            print("chewing: cannot create a libchewing context (data: %s)" % CHEWING_DATA_DIR, file=sys.stderr)
            return None
        self.userPhraseFallback = True
        if not _userPhraseWarningShown:
            _userPhraseWarningShown = True
            self.showMessage("無法開啟新酷音使用者詞庫，這次學到的詞不會儲存", 5)
        return chewingContext

    # 初始化新酷音輸入法引擎
    def initChewingContext(self):
        if self.chewingContext and self.userPhraseFallback and not self.isComposing():
            # 上次無法開啟使用者詞庫而暫時改用記憶體中的詞庫，重新啟用時再試一次
            self.rebuildChewingContext()
            return
        # load libchewing context
        if not self.chewingContext:
            cfg = chewingConfig  # 所有 ChewingTextService 共享一份設定物件
            chewingContext = self.createChewingContext()
            if not chewingContext:
                # 按鍵都直接交給應用程式；下次啟用或開啟鍵盤時再試
                return
            self.chewingContext = chewingContext
            chewingContext.set_maxChiSymbolLen(MAX_CHI_SYMBOL_LEN)  # 編輯區最多幾個字

            # 預設英數 or 中文模式
            if self.lastLangMode is not None:
                self.langMode = self.lastLangMode  # 恢復上次鍵盤暫時關閉時儲存的狀態
            else:
                self.langMode = ENGLISH_MODE if cfg.defaultEnglish else CHINESE_MODE
            chewingContext.set_ChiEngMode(self.langMode)

            # 預設全形 or 半形
            if self.lastShapeMode is not None:
                self.shapeMode = self.lastShapeMode  # 恢復上次鍵盤暫時關閉時儲存的狀態
            else:
                self.shapeMode = FULLSHAPE_MODE if cfg.defaultFullSpace else HALFSHAPE_MODE
            chewingContext.set_ShapeMode(self.shapeMode)

        self.applyConfig()  # 套用其餘的使用者設定

    # 輸入法被使用者啟用
    def onActivate(self):
        cfg = chewingConfig  # globally shared config object
        TextService.onActivate(self)
        self.initChewingContext()

        # 向系統宣告 Shift + Space 這個組合為特殊用途 (全半形切換)
        # 當 Shift + Space 被按下的時候，onPreservedKey() 會被呼叫
        # (設定停用時 onPreservedKey() 傳回 False，按鍵照常交給應用程式)
        self.addPreservedKey(VK_SPACE, TF_MOD_SHIFT,
                             SHIFT_SPACE_GUID)  # shift + space

        # 啟動時預設停用中文輸入 (限 Windows 8 以上適用)
        if self.client.isWindows8Above:
            self.setKeyboardOpen(not cfg.disableOnStartup)

        # 新增語言列按鈕 (Windows 8 之後 default 已取消語言列)
        if self.keyboardOpen:
            self.addLangButtons()

        # Windows 8 以上已取消語言列功能，改用 systray IME mode icon
        if self.client.isWindows8Above:
            # 切換中英文、簡繁體圖示
            if self.langMode == CHINESE_MODE:
                if self.getCapslockState() == True:
                    icon_name = "capsEng.ico"
                else:
                    icon_name = "traC.ico"
            else:
                icon_name = "eng.ico"
            self.addButton("windows-mode-icon",
                           icon=os.path.join(self.icon_dir, icon_name),
                           tooltip="中英文切換",
                           commandId=ID_MODE_ICON
                           )

    def addLangButtons(self):
        if self.hasLangButtons:
            return
        # 切換中英文、簡繁體
        if self.langMode == CHINESE_MODE:
            if self.getCapslockState() == True:
                icon_name = "capsEng.ico"
            else:
                icon_name = "traC.ico"
        else:
            icon_name = "eng.ico"
        self.addButton("switch-lang",
                       icon=os.path.join(self.icon_dir, icon_name),
                       tooltip="中英文切換",
                       commandId=ID_SWITCH_LANG
                       )

        # 切換全半形
        icon_name = "full.ico" if self.shapeMode == FULLSHAPE_MODE else "half.ico"
        self.addButton("switch-shape",
                       icon=os.path.join(self.icon_dir, icon_name),
                       tooltip="全形/半形切換",
                       commandId=ID_SWITCH_SHAPE
                       )

        # 設定
        self.addButton("settings",
                       icon=os.path.join(self.icon_dir, "config.ico"),
                       tooltip="設定",
                       type="menu"
                       )
        self.hasLangButtons = True

    def removeLangButtons(self):
        if self.hasLangButtons:
            self.removeButton("switch-lang")
            self.removeButton("switch-shape")
            self.removeButton("settings")
        self.hasLangButtons = False

    # 使用者離開輸入法
    def onDeactivate(self):
        TextService.onDeactivate(self)
        # 釋放 libchewing context 的資源
        self.closeChewingContext()
        self.lastKeyEvent = None

        # 丟棄輸入法狀態
        self.lastLangMode = None
        self.lastShapeMode = None

        # 移除語言列按鈕
        self.removeLangButtons()

        if self.client.isWindows8Above:
            self.removeButton("windows-mode-icon")

    def closeChewingContext(self):
        chewingContext = self.chewingContext
        self.chewingContext = None
        if chewingContext:
            chewingContext.close()

    # 設定是否啟用自動學習功能
    def setAutoLearn(self, autoLearn):
        if autoLearn:
            self.chewingContext.set_autoLearn(AUTOLEARN_ENABLED)
        else:
            self.chewingContext.set_autoLearn(AUTOLEARN_DISABLED)

    # 設定選字按鍵 (123456..., asdf....等等)
    def setSelKeys(self, selKeys):
        TextService.setSelKeys(self, selKeys)
        self.selKeys = selKeys
        if self.chewingContext:
            self.chewingContext.set_selKeys(selKeys)

    # 使用者按下按鍵，在 app 收到前先過濾那些鍵是輸入法需要的。
    # return True，系統會呼叫 onKeyDown() 進一步處理這個按鍵
    # return False，表示我們不需要這個鍵，系統會原封不動把按鍵傳給應用程式
    def filterKeyDown(self, keyEvent):
        cfg = chewingConfig
        # 紀錄最後一次按下的 keyEvent，在 filterKeyUp() 中要用
        self.lastKeyEvent = keyEvent
        if self.lastKeyDownTime == 0.0:
            self.lastKeyDownTime = time.time()

        # 無法建立新酷音引擎 (見 createChewingContext)：按鍵全部交給應用程式
        if not self.chewingContext:
            return False

        # 使用者開始輸入，還沒送出前的編輯區內容稱 composition string
        # isComposing() 是 False，表示目前沒有正在編輯中文
        # 另外，若使用 "`" key 輸入特殊符號，可能會有編輯區是空的，但選字清單開啟，輸入法需要處理的情況
        # 此時 isComposing() 也會是 True
        if self.isComposing():
            # 組字中按 Ctrl/Alt + 字母等是應用程式的快速鍵 (Ctrl+C、Ctrl+Z、Alt+F…)，
            # C++ 端送來的字元不含 Ctrl，以前會被當成注音 ('c' 變成ㄏ)
            if keyEvent.isPrintableChar() and (keyEvent.isKeyDown(VK_CONTROL) or keyEvent.isKeyDown(VK_MENU)):
                return self.isImeCtrlKey(keyEvent)
            return True
        # --------------   以下都是「沒有」正在輸入中文的狀況   --------------

        # libchewing 只處理 ASCII 字元，é、ß、€ (非美式鍵盤、AltGr) 以前會被吃掉
        if keyEvent.isPrintableChar() and keyEvent.charCode > 0x7E:
            return False

        # 如果按下 Alt，可能是應用程式熱鍵，輸入法不做處理
        if keyEvent.isKeyDown(VK_MENU):
            return False

        # 如果按下 Ctrl 鍵
        if keyEvent.isKeyDown(VK_CONTROL):
            # 開啟 Ctrl 快速輸入符號，輸入法需要此按鍵
            if cfg.easySymbolsWithCtrl and keyEvent.isPrintableChar() and self.langMode == CHINESE_MODE:
                return True
            else:  # 否則可能是應用程式熱鍵，輸入法不做處理
                return False

        # 若按下 Shift 鍵
        if keyEvent.isKeyDown(VK_SHIFT):
            # 若開啟 Shift 快速輸入符號，輸入法需要此按鍵
            if cfg.easySymbolsWithShift and keyEvent.isPrintableChar() and self.langMode == CHINESE_MODE:
                return True

        # 不論中英文模式，NumPad 都允許直接輸入數字，輸入法不處理
        if keyEvent.isKeyToggled(VK_NUMLOCK):  # NumLock is on
            # if this key is Num pad 0-9, +, -, *, /, pass it back to the system
            if keyEvent.keyCode >= VK_NUMPAD0 and keyEvent.keyCode <= VK_DIVIDE:
                return False  # bypass IME

        # 不管中英文模式，只要是全形可見字元或空白，輸入法都需要進一步處理 (半形轉為全形)
        if self.shapeMode == FULLSHAPE_MODE:
            return (keyEvent.isPrintableChar() or keyEvent.keyCode == VK_SPACE)

        # --------------   以下皆為半形模式   --------------

        # 如果是英文半形模式，輸入法不做任何處理
        if self.langMode == ENGLISH_MODE:
            return False
        # --------------   以下皆為中文模式   --------------

        # 中文模式下開啟 Capslock，須切換成英文
        if cfg.enableCapsLock and keyEvent.isKeyToggled(VK_CAPITAL):
            # 如果此按鍵是英文字母，中文模式下要從大寫轉小寫，需要輸入法處理
            if keyEvent.isChar() and chr(keyEvent.charCode).isalpha():
                return True
            # 是其他符號或數字，則視同英文模式，不用處理
            else:
                return False

        # 中文模式下，當中文編輯區是空的，輸入法只需處理注音符號和標點
        # 大略可用是否為 printable char 來檢查
        # 注意：此處不能直接寫死檢查按鍵是否為注音或標點，因為在不同 keyboard layout，例如
        # 倚天鍵盤或許氏...等，代表注音符號的按鍵全都不同
        if keyEvent.isPrintableChar() and keyEvent.keyCode != VK_SPACE:
            return True

        # 其餘狀況一律不處理，原按鍵輸入直接送還給應用程式
        return False

    # 組字中 Ctrl + 可見字元，輸入法要處理的只有 Ctrl + 數字 (加入自訂詞) 和
    # 開啟「Ctrl 快速輸入符號」時的 Ctrl + 字母；按著 Alt (含 AltGr) 的都交給應用程式
    def isImeCtrlKey(self, keyEvent):
        if keyEvent.isKeyDown(VK_MENU) or not keyEvent.isKeyDown(VK_CONTROL):
            return False
        charStr = chr(keyEvent.charCode)
        if charStr.isdigit():
            return True
        return bool(chewingConfig.easySymbolsWithCtrl) and self.langMode == CHINESE_MODE

    # 目前的候選字視窗每一列顯示幾個候選字 (上下鍵移動游標的步幅)
    def candidatesPerUiRow(self):
        cfg = chewingConfig
        layout = getattr(cfg, 'candidateLayout', 'horizontal')
        return 1 if layout == 'vertical' else getattr(cfg, 'candidatePerRow', 6)

    # Ctrl + Del 刪除詞彙、Ctrl + PageUp 提昇 / Ctrl + PageDown 降低詞頻
    def maintainUserPhrase(self, keyCode, target_phrase):
        phraseConnect = None
        try:
            # 詞庫被設定工具等鎖住時不能等太久：後端只有一個執行緒，預設的 5 秒會讓
            # 所有程式的輸入法一起卡住 (C++ 端 2 秒就逾時)
            phraseConnect = sqlite3.connect(chewingConfig.getUserPhrase(), timeout=0.2)
            cursor = phraseConnect.cursor()
            cursor.execute("SELECT * FROM userphrase_v1 WHERE phrase=:target_phrase", {"target_phrase": target_phrase})
            result = cursor.fetchone()
            if (result is None):
                if keyCode == VK_DELETE:
                    self.showMessage("詞彙「" + target_phrase + "」不存在，無法刪除", 2)
                elif keyCode == VK_NEXT:
                    self.showMessage("詞彙「" + target_phrase + "」不存在，無法降低詞頻", 2)
                elif keyCode == VK_PRIOR:
                    self.showMessage("詞彙「" + target_phrase + "」不存在，無法提昇詞頻", 2)
            else:
                if keyCode == VK_DELETE:
                    cursor.execute("DELETE FROM userphrase_v1 WHERE phrase=:target_phrase", {"target_phrase": target_phrase})
                    phraseConnect.commit()
                    self.showMessage("刪除「" + target_phrase + "」成功", 2)
                elif keyCode == VK_NEXT:
                    cursor.execute("UPDATE userphrase_v1 SET user_freq = 0 WHERE phrase=:target_phrase", {"target_phrase": target_phrase})
                    phraseConnect.commit()
                    self.showMessage("↓降低「" + target_phrase + "」詞頻成功", 2)
                elif keyCode == VK_PRIOR:
                    cursor.execute("UPDATE userphrase_v1 SET user_freq = 5000 WHERE phrase=:target_phrase", {"target_phrase": target_phrase})
                    phraseConnect.commit()
                    self.showMessage("↑提昇「" + target_phrase + "」詞頻成功", 2)
            cursor.close()
        except Exception as err:
            self.showMessage(str(err), 2)
        finally:
            if phraseConnect is not None:
                phraseConnect.close()

    def onKeyDown(self, keyEvent):
        chewingContext = self.chewingContext
        if not chewingContext:
            return False
        if self.compositionSyncPending:
            # 用語言列按鈕切換中英文之後的第一個按鍵：先更新畫面；組字因此結束時，
            # 這個按鍵要照沒有組字的情況重新判斷是否交給應用程式
            self.syncComposition()
            if not self.isComposing() and not self.filterKeyDown(keyEvent):
                return False
        cfg = chewingConfig
        charCode = keyEvent.charCode
        keyCode = keyEvent.keyCode
        charStr = chr(charCode)

        # 某些狀況下，需要暫時強制切成英文模式，之後再恢復
        temporaryEnglishMode = False
        oldLangMode = chewingContext.get_ChiEngMode()
        ignoreKey = False  # 新酷音是否須忽略這個按鍵
        keyHandled = False  # 輸入法是否有處理這個按鍵
        # 選字視窗有候選字 (只有注音字根時視窗也是開著的，但清單是空的)
        hasCandidates = self.showCandidates and bool(self.candidateList)

        # 使用 Ctrl 或 Shift 鍵做快速符號輸入 (easy symbol input)
        # 這裡的 easy symbol input，是定義在 swkb.dat 設定檔中的符號
        if cfg.easySymbolsWithShift and keyEvent.isKeyDown(VK_SHIFT):
            chewingContext.set_easySymbolInput(1)
        elif cfg.easySymbolsWithCtrl and keyEvent.isKeyDown(VK_CONTROL):
            chewingContext.set_easySymbolInput(1)
        else:
            chewingContext.set_easySymbolInput(0)

        # 若目前輸入的按鍵是可見字元 (字母、數字、標點、空白...等)
        if keyEvent.isPrintableChar():
            keyHandled = True
            invertCase = False  # 是否需要反轉大小寫

            # 中文模式下須特別處理 CapsLock 和 Shift 鍵
            if self.langMode == CHINESE_MODE:
                # 若開啟 Caps lock，需要暫時強制切換成英文模式
                if cfg.enableCapsLock and keyEvent.isKeyToggled(VK_CAPITAL):
                    temporaryEnglishMode = True
                    invertCase = True  # 大寫字母轉成小寫

                # 如果啟動半形符號模式，且輸入符號，則暫時切換為英文模式
                if not cfg.fullShapeSymbols and keyEvent.isSymbols():
                    temporaryEnglishMode = True

                # 若按下 Shift 鍵
                if keyEvent.isKeyDown(VK_SHIFT):
                    # 如果是英文字母
                    if charStr.isalpha():
                        # 如果不使用快速輸入符號功能，則暫時切成英文模式
                        if not cfg.easySymbolsWithShift:
                            temporaryEnglishMode = True  # 暫時切換成英文模式
                            if not cfg.upperCaseWithShift:  # 如果沒有開啟 Shift 輸入大寫英文
                                invertCase = True  # 大寫字母轉成小寫

                    # 如果不是英文字母
                    else:
                        # 如果不使用 Shift 輸入全形標點，則暫時切成英文模式
                        if not cfg.fullShapeSymbolsWithShift:
                            temporaryEnglishMode = True

            if self.langMode == ENGLISH_MODE:  # 英文模式
                chewingContext.handle_Default(charCode)
            elif temporaryEnglishMode:  # 原為中文模式，暫時強制切成英文
                chewingContext.set_ChiEngMode(ENGLISH_MODE)
                if invertCase:  # 先反轉大小寫，再送給新酷音引擎
                    charCode = ord(
                        charStr.lower() if charStr.isupper() else charStr.upper())
                chewingContext.handle_Default(charCode)
            else:  # 中文模式
                if charStr.isalpha():  # 英文字母 A-Z
                    # 如果開啟 Ctrl 或 Shift + A-Z 快速輸入符號 (easy symbols，定義在 swkb.dat)
                    # 則只接受大寫英文字母
                    if chewingContext.get_easySymbolInput():
                        charCode = ord(charStr.upper())
                    else:
                        charCode = ord(charStr.lower())
                    chewingContext.handle_Default(charCode)
                elif keyEvent.keyCode == VK_SPACE:  # 空白鍵
                    # 選字時接收到空白鍵 (只有注音字根、還沒有候選字時，空白鍵是一聲)
                    if hasCandidates and cfg.spaceKeyCandidatesAction == 1:
                        candCursor = self.candidateCursor  # 目前的游標位置
                        candCount = len(self.candidateList)  # 目前選字清單項目數
                        # 還沒到選字視窗底部，移動游標
                        if (candCursor + 1) < candCount:
                            candCursor += 1
                        else:
                            # 游標到選字視窗底部，游標重設為第一個
                            candCursor = 0
                            if (chewingContext.cand_hasNext()):
                                # 如果選字清單有下一頁，執行翻頁
                                chewingContext.handle_PageDown()
                            else:
                                # 選字清單到底，按下「下」，可以切換組字模式
                                chewingContext.handle_Down()

                        self.setCandidateCursor(candCursor)
                    # 設定使用空白鍵輸出空格，在選字時直接處理空白才能翻頁
                    elif hasCandidates and cfg.spaceKeyAction == 0:
                        chewingContext.handle_Space()

                    # NOTE: libchewing 有 bug: 當啟用 "使用空白鍵選字" 時，chewing_handle_Space()
                    # 會忽略空白鍵，造成打不出空白。因此在此只有當 composition string 有內容
                    # 有需要選字時，才呼叫 handle_Space()，否則改用 handle_Default()，以免空白鍵被吃掉
                    elif self.isComposing():
                        chewingContext.handle_Space()
                    else:
                        chewingContext.handle_Default(charCode)
                # Ctrl + 數字 (0-9)
                elif keyEvent.isKeyDown(VK_CONTROL) and charStr.isdigit():
                    chewingContext.handle_CtrlNum(charCode)
                elif keyEvent.isKeyToggled(VK_NUMLOCK) and keyCode >= VK_NUMPAD0 and keyCode <= VK_DIVIDE:
                    # NumLock 開啟，處理 NumPad 按鍵
                    chewingContext.handle_Numlock(charCode)
                else:  # 其他按鍵不需要特殊處理
                    chewingContext.handle_Default(charCode)
        else:  # 不可見字元 (方向鍵、Enter、PageDown...等等)
            # 如果選字視窗有候選字。只有注音字根時視窗也開著但清單是空的，按鍵要交給
            # libchewing (以前 Enter 會送出 selKeys[0] 把ㄋ變成ㄅ、End 讓游標變成 -1)
            if hasCandidates:
                candCount = len(self.candidateList)  # 目前選字清單項目數
                candCursor = min(max(self.candidateCursor, 0), candCount - 1)  # 目前的游標位置

                # 處理詞彙 Ctrl + Del、刪除詞彙、Ctrl + PageUp 提昇/ Ctrl + PageDown 降低詞頻
                if keyEvent.isKeyDown(VK_CONTROL) and (keyCode == VK_DELETE or keyCode == VK_NEXT or keyCode == VK_PRIOR):
                    self.maintainUserPhrase(keyCode, self.candidateList[candCursor])
                    ignoreKey = keyHandled = True

                # 處理 Home、End 鍵，移到選字視窗的第一和最後一個字
                if keyCode == VK_HOME:
                    candCursor = 0
                    ignoreKey = keyHandled = True
                elif keyCode == VK_END:
                    candCursor = candCount - 1
                    ignoreKey = keyHandled = True

                # 使用左右鍵移動游標選字
                if cfg.leftRightAction == 0:
                    if keyCode == VK_LEFT:
                        if candCursor > 0:
                            candCursor -= 1
                            ignoreKey = keyHandled = True
                        else:  # 如果選字清單沒有下一頁，重設游標為最後一個，讓左右鍵可以循環移動游標
                            candCursor = candCount - 1

                    elif keyCode == VK_RIGHT:
                        if (candCursor + 1) < candCount:
                            candCursor += 1
                            ignoreKey = keyHandled = True
                        else:  # 如果選字清單沒有下一頁，重設游標為第一個，讓左右鍵可以循環移動游標
                            candCursor = 0

                # 使用上下鍵游標選字，因上下鍵需要作為組字模式切換，所以不設定循環
                # 步幅是候選窗一列的字數 (橫排一列是 candidatePerRow 個)
                if cfg.upDownAction == 0:
                    perRow = self.candidatesPerUiRow()
                    if keyCode == VK_UP:
                        if candCursor >= perRow:
                            candCursor -= perRow
                            ignoreKey = keyHandled = True
                    elif keyCode == VK_DOWN:
                        if (candCursor + perRow) < candCount:
                            candCursor += perRow
                            ignoreKey = keyHandled = True

                # 使用上下鍵翻頁，左右鍵新酷音預設為翻頁動作
                if cfg.upDownAction == 1:
                    if keyCode == VK_UP:
                        chewingContext.handle_PageUp()
                        keyHandled = True
                    elif keyCode == VK_DOWN:
                        if chewingContext.cand_hasNext():
                            chewingContext.handle_PageDown()
                            keyHandled = True

                # 按下 Enter 鍵
                if keyCode == VK_RETURN:
                    # 找出目前游標位置的選字鍵 (1234..., asdf...等等)
                    selKey = cfg.getSelKeys()[candCursor]
                    # 代替使用者送出選字鍵給新酷音引擎，進行選字
                    chewingContext.handle_Default(ord(selKey))
                    keyHandled = True
                # 更新選字視窗游標位置
                self.setCandidateCursor(candCursor)

            # 按鍵還沒被處理過
            if not keyHandled:
                # the candidate window does not need the key. pass it to libchewing.
                keyName = keyNames.get(keyCode)  # 取得按鍵的名稱
                if keyName:  # call libchewing method for the key
                    # 依照按鍵名稱，找 libchewing 對應的 handle_按鍵 () method 呼叫
                    methodName = "handle_" + keyName
                    method = getattr(chewingContext, methodName)
                    method()
                    keyHandled = True
                else:  # 我們不需要處理的按鍵，直接忽略
                    ignoreKey = True

        # 新酷音引擎忽略不處理此按鍵
        if keyHandled and chewingContext.keystroke_CheckIgnore():
            ignoreKey = True

        if not ignoreKey:  # 如果這個按鍵是有意義的，新酷音有做處理 (不可忽略)
            candidates = []
            # 處理選字清單
            if chewingContext.cand_TotalChoice() > 0:  # 若有候選字/詞
                # 要求新酷音引擎列出每個候選字
                chewingContext.cand_Enumerate()
                for i in range(chewingContext.cand_ChoicePerPage()):
                    if not chewingContext.cand_hasNext():
                        break
                    # 新酷音返回的是 UTF-8 byte string，須轉成 python 字串
                    cand = decodeText(chewingContext.cand_String())
                    candidates.append(cand)

                # 檢查選字清單是否改變 (沒效率但是簡單)
                if candidates != self.candidateList:
                    self.setCandidateList(candidates)  # 更新候選字清單
                    self.setShowCandidates(True)
                    # 換了清單一定要重設游標：以前上下左右都設成翻頁時不重設，游標停在
                    # 上一頁的位置 (超出清單)，Enter 送出的字和反白的不一樣或完全沒反應
                    if keyCode == VK_LEFT and cfg.leftRightAction == 0:
                        # 左鍵循環移動到前一頁，游標設為最後一個
                        self.setCandidateCursor(len(candidates) - 1)
                    else:  # 其他按鍵重設游標為第一個
                        self.setCandidateCursor(0)

                if not self.showCandidates:  # 如果目前沒有顯示選字視窗
                    self.setShowCandidates(True)  # 顯示選字視窗
            else:  # 沒有候選字
                if self.showCandidates:
                    self.setShowCandidates(False)  # 隱藏選字視窗
                    self.setCandidateList([])  # 更新候選字清單

            # 有輸入完成的中文字串要送出 (commit) 到應用程式
            if chewingContext.commit_Check():
                commitStr = decodeText(chewingContext.commit_String())

                self.setCommitString(commitStr)  # 設定要輸出的 commit string

            # 編輯區正在輸入中，尚未送出的中文字串 (composition string)
            compStr = ""
            if chewingContext.buffer_Check():
                compStr = decodeText(chewingContext.buffer_String())

            # 輸入到一半，還沒組成字的注音符號 (bopomofo)
            bopomofoStr = ""
            if chewingContext.bopomofo_Check():
                bopomofoStr = decodeText(chewingContext.bopomofo_String(None))
            compositionCursor = chewingContext.cursor_Current()

            # libchewing 有時會把注音從 bopomofo buffer 移到 composition buffer。
            # 對新版候選窗來說，這仍是字根提示，應顯示在 header 而不是輸入欄位。
            visibleCompStr, compRootStr = splitTrailingBopomofo(compStr)
            rootStr = bopomofoStr or compRootStr

            # 新式與傳統候選窗的打字方式相同 (傳統新酷音)：組好的字顯示在輸入欄位、
            # 由 libchewing 自動選詞，按 ↓ 或空白鍵才開選字窗，Enter 送出。
            # 以前新式樣式每打完一個音就自動開選字窗，聲調鍵 3/4/6/7 變成選字鍵
            # (你是 → 禰)、Backspace 刪不掉字、組字只顯示在候選窗裡
            if rootStr:
                self.setCompositionString(visibleCompStr)
                if not visibleCompStr:
                    self.currentReply["compositionString"] = "\u200b"
                    self.setCompositionCursor(0)
                else:
                    self.setCompositionCursor(min(compositionCursor, len(visibleCompStr)))
                self.updateCandidateHeader(rootStr, forceWindow=True)
            else:
                self.setCompositionString(visibleCompStr)
                self.setCompositionCursor(compositionCursor)

            # 顯示額外提示訊息 (例如：Ctrl+ 數字加入自訂詞之後，會顯示提示)
            if chewingContext.aux_Check():
                message = decodeText(chewingContext.aux_String())
                # FIXME: sometimes libchewing shows the same aux info
                # for subsequent key events... I think this is a bug.
                self.showMessage(message, 2)

        # 若先前有暫時強制切成英文模式，需要復原
        if temporaryEnglishMode:
            chewingContext.set_ChiEngMode(oldLangMode)

        # 依照目前狀態，更新語言列顯示的圖示
        self.updateLangButtons()

        if "candidateList" in self.currentReply or "showCandidates" in self.currentReply:
            if "candidateHeader" not in self.currentReply and self.currentReply.get("showCandidates", True):
                self.updateCandidateHeader()
            self.customizeCandidateUI()

        return keyHandled  # 告知系統我們是否有處理這個按鍵

    # 使用者放開按鍵，在 app 收到前先過濾那些鍵是輸入法需要的。
    # return True，系統會呼叫 onKeyUp() 進一步處理這個按鍵
    # return False，表示我們不需要這個鍵，系統會原封不動把按鍵傳給應用程式
    def filterKeyUp(self, keyEvent):
        # 最後按下和放開都是 Shift 鍵
        # (Ctrl + Shift、Alt + Shift 是切換輸入法 / 鍵盤配置的快速鍵，不能切換中英文)
        if self.lastKeyEvent and self.lastKeyEvent.keyCode == VK_SHIFT and keyEvent.keyCode == VK_SHIFT \
                and not self.isModifierHeld(keyEvent) and not self.isModifierHeld(self.lastKeyEvent):
            # 若啟用使用 Shift 在打字時移動游標，呼叫 onKeyUp()
            if chewingConfig.shiftMoveCursor:
                return True

            # 若啟用使用 Shift 鍵切換中英文模式
            if chewingConfig.switchLangWithShift:
                # 檢查使用者當前的設定，是使用哪一邊的 Shift 來切換中英文模式
                if chewingConfig.switchLangWithWhichShift == SWITCH_LANG_WITH_BOTH_SHIFT:
                    pass
                elif chewingConfig.switchLangWithWhichShift == SWITCH_LANG_WITH_LEFT_SHIFT and not self.isShiftSide(keyEvent, VK_LSHIFT):
                    self.lastKeyDownTime = 0.0
                    return False
                elif chewingConfig.switchLangWithWhichShift == SWITCH_LANG_WITH_RIGHT_SHIFT and not self.isShiftSide(keyEvent, VK_RSHIFT):
                    self.lastKeyDownTime = 0.0
                    return False

                pressedDuration = time.time() - self.lastKeyDownTime
                # 按下和放開的時間相隔 < 0.5 秒
                if pressedDuration < 0.5:
                    self.toggleLanguageMode()  # 切換中英文模式
                    if self.compositionSyncPending:
                        return True  # onKeyUp() 有 edit session，才能更新畫面上的組字

        # 按下 Capslcok 會切換圖示
        if chewingConfig.enableCapsLock and self.lastKeyEvent:
            if self.isPressed(VK_CAPITAL):
                self.updateSwitchLangIcon = True
                self.updateLangButtons()

        self.lastKeyDownTime = 0.0
        return False

    # https://docs.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getasynckeystate
    # 當 keyCode 對應的按鍵、曾被按下觸發過，GetAsyncKeyState() 的回傳值會 >= 1
    def isPressed(self, keyCode):
        return windll.user32.GetAsyncKeyState(keyCode) >= 1

    def isModifierHeld(self, keyEvent):
        return keyEvent.isKeyDown(VK_CONTROL) or keyEvent.isKeyDown(VK_MENU)

    # 放開的 Shift 是不是 sideVk (VK_LSHIFT/VK_RSHIFT) 那一邊。優先用按鍵事件的掃描碼：
    # 放開時鍵已經彈起，isPressed() 只剩 GetAsyncKeyState「上次查詢後按過」的位元，
    # 微軟文件說它不可靠 (用左 Shift 打過大寫後，按右 Shift 也會被當成左邊)。
    # 掃描碼不是這兩個值 (SendInput 模擬的按鍵) 時退回原本的判斷
    def isShiftSide(self, keyEvent, sideVk):
        scanCode = getattr(keyEvent, 'scanCode', 0)
        if scanCode in (LEFT_SHIFT_SCAN_CODE, RIGHT_SHIFT_SCAN_CODE):
            return scanCode == (LEFT_SHIFT_SCAN_CODE if sideVk == VK_LSHIFT else RIGHT_SHIFT_SCAN_CODE)
        return self.isPressed(sideVk)

    # 取得 Capslock 按鍵狀態
    def getCapslockState(self):
        if ((windll.user32.GetKeyState(VK_CAPITAL) & 0x0001) != 0):
            return True
        else:
            return False

    def onKeyUp(self, keyEvent):
        if not self.chewingContext:
            return False
        if self.compositionSyncPending:  # 剛用 Shift 切換中英文
            self.syncComposition()
            self.lastKeyDownTime = 0.0
            return True
        pressedDuration = time.time() - self.lastKeyDownTime
        if pressedDuration < 0.5 and self.isComposing() and not self.chewingContext.bopomofo_Check():
            if self.lastKeyEvent:
                if self.lastKeyEvent.isKeyDown(VK_RSHIFT) and self.compositionCursor < len(self.compositionString):
                    self.chewingContext.handle_Right()
                    self.setCompositionCursor(
                        self.chewingContext.cursor_Current())
                if self.lastKeyEvent.isKeyDown(VK_LSHIFT) and self.compositionCursor > 0:
                    self.chewingContext.handle_Left()
                    self.setCompositionCursor(
                        self.chewingContext.cursor_Current())

            self.lastKeyDownTime = 0.0
            return True
        else:
            return False

    def onPreservedKey(self, guid):
        self.lastKeyEvent = None
        # some preserved keys registered are pressed
        if guid == SHIFT_SPACE_GUID:  # 使用者按下 shift + space
            # 停用「Shift + 空白鍵切換全半形」時不處理，空白照常送給應用程式
            # (以前傳回 True，按鍵被吃掉，什麼都沒發生)
            if not chewingConfig.enableShiftSpace or not self.chewingContext:
                return False
            self.toggleShapeMode()  # 切換全半形
            return True
        return False

    # 使用者按下語言列按鈕
    def onCommand(self, commandId, commandType):
        print("onCommand", commandId, commandType)
        # FIXME: We should distinguish left and right click using commandType
        if commandId == ID_SWITCH_LANG and commandType == COMMAND_LEFT_CLICK:  # 切換中英文模式
            self.toggleLanguageMode()
        elif commandId == ID_SWITCH_SHAPE and commandType == COMMAND_LEFT_CLICK:  # 切換全形/半形
            self.toggleShapeMode()
        elif commandId == ID_SETTINGS or commandId == ID_USER_PHRASE_EDITOR:  # 開啟設定工具 or 編輯辭庫
            if commandId == ID_USER_PHRASE_EDITOR:  # 編輯使用者辭庫
                tool_name = "user_phrase_editor"
            else:  # 輸入法設定
                tool_name = "config_tool"
            config_tool = '"{0}" {1}'.format(os.path.join(
                self.curdir, "config_tool.py"), tool_name)
            python_exe = sys.executable  # 找到 python 執行檔
            # 使用我們自帶的 python runtime exe 執行 config tool
            # 此處也可以用 subprocess，不過使用 windows API 比較方便
            # SW_HIDE = 0 (hide the window)
            r = windll.shell32.ShellExecuteW(
                None, "open", python_exe, config_tool, self.curdir, 0)
        elif commandId == ID_MODE_ICON:  # windows 8 mode icon
            self.toggleLanguageMode()  # 切換中英文模式
        elif commandId == ID_ABOUT:  # 關於新酷音輸入法
            pass
        elif commandId == ID_WEBSITE:  # visit chewing website
            os.startfile("http://chewing.im/")
        elif commandId == ID_GROUP:  # visit chewing google groups website
            os.startfile("http://groups.google.com/group/chewing-devel")
        elif commandId == ID_BUGREPORT:  # visit bug tracker page
            os.startfile("https://github.com/omni624562/WIME/issues")
        elif commandId == ID_DICT_BUGREPORT:
            os.startfile("https://github.com/chewing/libchewing/issues")
        elif commandId == ID_MOEDICT:  # a very awesome online Chinese dictionary
            os.startfile("https://www.moedict.tw/")
        # 教育部辭典 2021 年改版後的網址 (舊的 http 路徑要先經過明碼 http 轉址)
        elif commandId == ID_SIMPDICT:  # a simplified version of the online dictonary
            os.startfile("https://dict.concised.moe.edu.tw/")
        elif commandId == ID_LITTLEDICT:  # a simplified dictionary for little children
            os.startfile("https://dict.mini.moe.edu.tw/")
        elif commandId == ID_PROVERBDICT:  # a dictionary for proverbs
            os.startfile(
                "https://dict.idioms.moe.edu.tw/")
        elif commandId == ID_CHEWING_HELP:
            pass
    # 開啟語言列按鈕選單
    def onMenu(self, buttonId):
        # 設定按鈕 (windows 8 mode icon 按鈕也使用同一個選單)
        if buttonId == "settings" or buttonId == "windows-mode-icon":
            # 用 json 語法表示選單結構
            return [
                # {"text": "關於新酷音輸入法 (&A)", "id": ID_ABOUT},
                {"text": "新酷音官方網站 (&W)", "id": ID_WEBSITE},
                {"text": "新酷音線上討論區 (&G)", "id": ID_GROUP},
                {},
                {"text": "軟體本身的建議及錯誤回報 (&B)", "id": ID_BUGREPORT},
                {"text": "注音及選字選詞錯誤回報 (&P)", "id": ID_DICT_BUGREPORT},
                {},
                # {"text": "新酷音使用說明 (&H)", "id": ID_CHEWING_HELP},
                {"text": "編輯使用者詞庫 (&E)", "id": ID_USER_PHRASE_EDITOR},
                {"text": "設定新酷音輸入法 (&C)", "id": ID_SETTINGS},
                {},
                {"text": "網路辭典 (&D)", "submenu": [
                    {"text": "萌典 (moedict)", "id": ID_MOEDICT},
                    {},
                    {"text": "教育部國語辭典簡編本", "id": ID_SIMPDICT},
                    {"text": "教育部國語小字典", "id": ID_LITTLEDICT},
                    {"text": "教育部成語典", "id": ID_PROVERBDICT},
                ]}
            ]
        return None

    # 依照目前輸入法狀態，更新語言列
    def updateLangButtons(self):
        chewingContext = self.chewingContext
        if not chewingContext:
            return
        langMode = chewingContext.get_ChiEngMode()

        # 如果中英文模式、簡繁模式發生改變
        if langMode != self.langMode or self.updateSwitchLangIcon:
            self.updateSwitchLangIcon = False
            self.langMode = langMode
            if langMode == CHINESE_MODE:
                if self.getCapslockState() == True:
                   icon_name = "capsEng.ico"
                else:
                    icon_name = "traC.ico"
            else:
                icon_name = "eng.ico"
            icon_path = os.path.join(self.icon_dir, icon_name)
            if self.hasLangButtons:
                self.changeButton("switch-lang", icon=icon_path)

            if self.client.isWindows8Above:  # windows 8 mode icon
                # FIXME: we need a better set of icons to meet the
                #        WIndows 8 IME guideline and UX guidelines.
                self.changeButton("windows-mode-icon", icon=icon_path)

        shapeMode = chewingContext.get_ShapeMode()
        if shapeMode != self.shapeMode:  # 如果全形半形模式改變
            self.shapeMode = shapeMode
            if self.hasLangButtons:
                icon_name = "full.ico" if shapeMode == FULLSHAPE_MODE else "half.ico"
                icon_path = os.path.join(self.icon_dir, icon_name)
                self.changeButton("switch-shape", icon=icon_path)

    # 切換中英文模式
    def toggleLanguageMode(self):
        chewingContext = self.chewingContext
        if chewingContext:
            if chewingContext.get_ChiEngMode() == CHINESE_MODE:
                new_mode = ENGLISH_MODE
            else:
                new_mode = CHINESE_MODE
            chewingContext.set_ChiEngMode(new_mode)
            # 切換中英文時還沒組成字的注音要丟掉，只顯示注音字根的視窗也要關掉。以前
            # 視窗一直開著，之後的 Enter 送出 "1"、Backspace 全被吃掉。
            # filterKeyUp / onCommand 的回覆沒有 edit session，C++ 端不會更新組字，
            # 所以畫面留到 onKeyUp 或下一個 onKeyDown 再更新 (syncComposition)
            if chewingContext.bopomofo_Check():
                chewingContext.clean_bopomofo_buf()
            if self.showCandidates and not self.candidateList:
                self.compositionSyncPending = True
            self.updateLangButtons()

    # 把 Python 端與畫面上的組字狀態更新成 libchewing 目前的內容
    def syncComposition(self):
        self.compositionSyncPending = False
        chewingContext = self.chewingContext
        if not chewingContext:
            return
        compStr = decodeText(chewingContext.buffer_String()) if chewingContext.buffer_Check() else ""
        visibleCompStr = splitTrailingBopomofo(compStr)[0]
        if not self.candidateList:  # 只顯示注音字根的視窗 (或重建引擎前留下的視窗)
            self.setShowCandidates(False)
            self.setCandidateCursor(0)
        self.setCompositionString(visibleCompStr)
        self.setCompositionCursor(min(chewingContext.cursor_Current(), len(visibleCompStr)))

    # 切換全形/半形 (Shift + 空白鍵是否可以切換，由 onPreservedKey() 檢查；
    # 以前在這裡檢查，停用快速鍵時連語言列的全/半形按鈕也失效)
    def toggleShapeMode(self):
        chewingContext = self.chewingContext
        if chewingContext:
            if chewingContext.get_ShapeMode() == HALFSHAPE_MODE:
                new_mode = FULLSHAPE_MODE
            else:
                new_mode = HALFSHAPE_MODE
            chewingContext.set_ShapeMode(new_mode)
            self.updateLangButtons()

    # 鍵盤開啟/關閉時會被呼叫 (在 Windows 10 Ctrl+Space 時)
    def onKeyboardStatusChanged(self, opened):
        TextService.onKeyboardStatusChanged(self, opened)
        if opened:  # 鍵盤開啟
            self.initChewingContext()  # 確保新酷音引擎啟動
            self.addLangButtons()
        else:  # 鍵盤關閉，輸入法停用
            # 若選字中，隱藏選字視窗
            if self.showCandidates:
                self.setShowCandidates(False)

            # 備份目前狀態 (下次重新開啟時套用)
            self.lastLangMode = self.langMode
            self.lastShapeMode = self.shapeMode

            # self.hideMessage() # hide message window, if there's any
            self.closeChewingContext()  # 釋放新酷音引擎資源
            # disable 其他語言列按鈕
            self.removeLangButtons()

        # Windows 8 systray IME mode icon
        if self.client.isWindows8Above:
            # 若鍵盤關閉，我們需要把 widnows 8 mode icon 設定為 disabled
            self.changeButton("windows-mode-icon", enable=opened)
        self.updateLangButtons()

    # 當中文編輯結束時會被呼叫。若中文編輯不是正常結束，而是因為使用者
    # 切換到其他應用程式或其他原因，導致我們的輸入法被強制關閉，此時
    # forced 參數會是 True，在這種狀況下，要清除一些 buffer
    def onCompositionTerminated(self, forced):
        TextService.onCompositionTerminated(self, forced)
        self.compositionSyncPending = False
        if forced:
            # 中文組字到一半被系統強制關閉，清除編輯區內容
            chewingContext = self.chewingContext
            if chewingContext:
                if self.showCandidates:
                    chewingContext.cand_close()
                    self.setShowCandidates(False)
                if chewingContext.bopomofo_Check():
                    chewingContext.clean_bopomofo_buf()
                if chewingContext.buffer_Check():
                    chewingContext.commit_preedit_buf()

    def onKillFocus(self):
        self.compositionSyncPending = False
        chewingContext = self.chewingContext
        wasShowingCandidates = self.showCandidates
        if chewingContext:
            if wasShowingCandidates:
                chewingContext.cand_close()
            if chewingContext.bopomofo_Check():
                chewingContext.clean_bopomofo_buf()
            if chewingContext.buffer_Check():
                chewingContext.clean_preedit_buf()
        TextService.onKillFocus(self)
        self.setShowCandidates(False)
        self.setCandidateList([])
        self.setCandidateCursor(0)
