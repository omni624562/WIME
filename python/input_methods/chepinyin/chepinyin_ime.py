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


class ChePinyinTextService(CinBaseTextService):
    IME_DIR_NAME   = "chepinyin"
    MAX_CHAR_LENGTH = 7
    CIN_FILE_LIST  = ["thpinyin.json", "pinyin.json", "roman.json"]

    def __init__(self, client):
        super().__init__(client, CinTable, RCinTable, HCinTable)

    def checkConfigChange(self):
        super().checkConfigChange()
        if self.cfg.selCinType == 0 or self.cfg.selCinType == 1 or self.cfg.selCinType == 2:
            if not self.useEndKey or not self.endKeyList:
                self.endKeyList = ["1", "2", "3", "4", "5"]
                self.useEndKey = True
        else:
            self.useEndKey = False


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
