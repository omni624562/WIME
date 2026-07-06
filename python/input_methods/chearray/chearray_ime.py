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


class CheArrayTextService(CinBaseTextService):
    IME_DIR_NAME   = "chearray"
    MAX_CHAR_LENGTH = 4
    CIN_FILE_LIST  = ["tharray.json", "array30.json", "ar30-big.json", "array40.json"]

    def __init__(self, client):
        super().__init__(client, CinTable, RCinTable, HCinTable)

    def onKeyDown(self, keyEvent):
        if self.cfg.selCinType == 0 or self.cfg.selCinType == 2:
            self.maxCharLength = 5
        else:
            self.maxCharLength = 4

        if self.cfg.selCinType == 1 and self.compositionChar == 'w' and self.cinbase.isNumberChar(keyEvent.keyCode):
            if self.cin.isInCharDef('w' + chr(keyEvent.charCode)):
                self.compositionChar += chr(keyEvent.charCode)
                self.setCompositionString(self.compositionString + chr(keyEvent.charCode))
                self.setCompositionCursor(len(self.compositionString))
                self.canUseNumberKey = False

        KeyState = super().onKeyDown(keyEvent)
        self.canUseNumberKey = True
        return KeyState


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
