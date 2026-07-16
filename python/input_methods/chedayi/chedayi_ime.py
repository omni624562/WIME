#! python3
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
from cinbase.ime_base import CinBaseTextService


class CheDayiTextService(CinBaseTextService):
    IME_DIR_NAME   = "chedayi"
    MAX_CHAR_LENGTH = 4
    CIN_FILE_LIST  = ["thdayi.json", "dayi4.json", "dayi3.json"]

    def __init__(self, client):
        super().__init__(client, CinTable, RCinTable, HCinTable)

    def initTextServiceExtra(self):
        # 必須在 initCinBaseContext 之前設好，dsymbols 標點符號表才會載入
        self.useDayiSymbols = True
        self.selDayiSymbolCharType = 0

    def onKeyDown(self, keyEvent):
        if self.cfg.selCinType == 0 or self.cfg.selCinType == 1:
            self.maxCharLength = 4
        elif self.cfg.selCinType == 2:
            self.maxCharLength = 3

        charCode = keyEvent.charCode
        keyCode = keyEvent.keyCode
        charStr = chr(charCode)

        # 大易符號
        self.DayiSymbolChar = "=" if self.selDayiSymbolCharType == 0 else "'"
        self.DayiSymbolString = "＝" if self.selDayiSymbolCharType == 0 else "號"

        if self.langMode == 1 and not self.showmenu:
            if len(self.compositionChar) == 0 and not self.phrasemode and charStr == self.DayiSymbolChar and not keyEvent.isKeyDown(VK_CONTROL):
                self.compositionChar += charStr
                self.dayisymbolsmode = True
                if self.compositionBufferMode:
                    self.cinbase.setCompositionBufferString(self, self.DayiSymbolString, 0)
                else:
                    self.setCompositionString(self.DayiSymbolString)
            elif self.dayisymbolsmode and self.isShowCandidates:
                self.canUseSelKey = True
            elif len(self.compositionChar) >= 1 and self.dayisymbolsmode:
                if self.dsymbols.isInCharDef(self.compositionChar[1:] + charStr):
                    self.compositionChar += charStr
                    self.canUseSelKey = False
                    candidates = self.dsymbols.getCharDef(self.compositionChar[1:])

        if not self.directShowCand:
            self.autoShowCandWhenMaxChar = True
        return super().onKeyDown(keyEvent)


class CinTable:
    loading = False
    def __init__(self):
        self.cin = None
        self.curCinType = None
        self.userExtendTable = None
        self.priorityExtendTable = None
        self.ignorePrivateUseArea = None
CinTable = CinTable()


class RCinTable:
    loading = False
    def __init__(self):
        self.cin = None
        self.curCinType = None
RCinTable = RCinTable()


class HCinTable:
    loading = False
    def __init__(self):
        self.cin = None
        self.curCinType = None
HCinTable = HCinTable()
