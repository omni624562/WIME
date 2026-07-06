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

from cinbase.ime_base import CinBaseTextService


class ChePhoneticTextService(CinBaseTextService):
    IME_DIR_NAME   = "chephonetic"
    MAX_CHAR_LENGTH = 4
    CIN_FILE_LIST  = ["thphonetic.json", "CnsPhonetic.json", "bpmf.json"]

    def __init__(self, client):
        super().__init__(client, CinTable, RCinTable, HCinTable)

        self.keyboardLayout = self.cfg.keyboardLayout
        self.kbtypelist = [
            "1qaz2wsxedcrfv5tgbyhnujm8ik,9ol.0p;/-7634",    # standard kb
            "bpmfdtnlvkhg7c,./j;'sexuaorwiqzy890-=1234",    # ET
            "1234567890-qwertyuiopasdfghjkl;zxcvbn/m,.",    # IBM
            "2wsx3edcrfvtgb6yhnujm8ik,9ol.0p;/-['=1qaz"     # Gin-yieh
        ]
        self.zhuintab = [
            "1qaz2wsxedcrfv5tgbyhn",    # ㄅㄆㄇㄈㄉㄊㄋㄌㄍㄎㄏㄐㄑㄒㄓㄔㄕㄖㄗㄘㄙ
            "ujm",                      # ㄧㄨㄩ
            "8ik,9ol.0p;/-",            # ㄚㄛㄜㄝㄞㄟㄠㄡㄢㄣㄤㄥㄦ
            "7634"                      # ˙ˊˇˋ
        ]

        self.useEndKey = True
        self.autoShowCandWhenMaxChar = True
        self.endKeyList = []
        self.endKey = self.kbtypelist[self.keyboardLayout][-4:]
        for key in self.endKey:
            self.endKeyList.append(key)

    def checkConfigChange(self):
        super().checkConfigChange()
        if not self.keyboardLayout == self.cfg.keyboardLayout:
            self.keyboardLayout = self.cfg.keyboardLayout
            self.endKeyList = []
            self.endKey = self.kbtypelist[self.keyboardLayout][-4:]
            for key in self.endKey:
                self.endKeyList.append(key)

    def updateCompositionChar(self, charStr):
        compositionChar = ['', '', '', '']
        charLength = len(self.compositionChar)

        for c in self.compositionChar:
            if c in self.zhuintab[0]:
                compositionChar[0] = c
            elif c in self.zhuintab[1]:
                compositionChar[1] = c
            elif c in self.zhuintab[2]:
                compositionChar[2] = c
            elif c in self.zhuintab[3]:
                compositionChar[3] = c

        if charStr in self.zhuintab[0]:
            compositionChar[0] = charStr
        elif charStr in self.zhuintab[1]:
            compositionChar[1] = charStr
        elif charStr in self.zhuintab[2]:
            compositionChar[2] = charStr
        elif charStr in self.zhuintab[3]:
            compositionChar[3] = charStr

        keynames = ''
        compchar = ''
        for i in compositionChar:
            if not i == '':
                compchar += i
                keynames += self.cin.getKeyName(i)

        self.compositionChar = compchar
        if self.compositionBufferMode:
            self.cinbase.setCompositionBufferString(self, keynames, charLength)
        else:
            self.setCompositionString(keynames)
            self.setCompositionCursor(len(self.compositionString))


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
