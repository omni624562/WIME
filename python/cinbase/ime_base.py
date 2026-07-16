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

import copy
import os.path
import sys

from textService import TextService
from cinbase import CinBase, LoadCinTable
from cinbase.config import CinBaseConfig


class CinBaseTextService(TextService):
    """Shared base for all CinBase-backed che* IMEs.

    Subclasses must define three class attributes:
        IME_DIR_NAME   = "checj"          # directory name under input_methods/
        MAX_CHAR_LENGTH = 5               # maximum composition length
        CIN_FILE_LIST   = ["checj.json"]  # ordered list of CIN filenames

    The subclass __init__ must pass the three module-level table singletons:
        super().__init__(client, CinTable, RCinTable, HCinTable)

    Extra subclass-specific __init__ work (e.g. keyboard layout setup) goes
    *after* the super().__init__() call; self.cfg is available at that point.

    Override checkConfigChange() or other methods as needed, calling
    super().checkConfigChange() first to run the common logic.
    """

    compositionChar = ''
    IME_DIR_NAME = ""
    MAX_CHAR_LENGTH = 1
    CIN_FILE_LIST = []

    def __init__(self, client, cin_table, rcin_table, hcin_table):
        TextService.__init__(self, client)

        self.imeDirName = self.IME_DIR_NAME
        self.maxCharLength = self.MAX_CHAR_LENGTH
        self.cinFileList = list(self.CIN_FILE_LIST)

        self.cinbase = CinBase
        # Resolve curdir from the subclass's module file, not this base module.
        mod = sys.modules.get(type(self).__module__)
        self.curdir = os.path.abspath(os.path.dirname(mod.__file__)) if mod else ""

        # Store table references so all methods can use them without arguments.
        self._cin_table = cin_table
        self._rcin_table = rcin_table
        self._hcin_table = hcin_table

        self.cinbase.initTextService(self, TextService)
        # 子類別的自訂旗標（如大易的 useDayiSymbols）必須在 initCinBaseContext
        # 之前設定，否則 context 初始化不會載入對應的資料表
        self.initTextServiceExtra()

        CinBaseConfig.__init__()
        self.configVersion = CinBaseConfig.getVersion()
        self.cfg = copy.deepcopy(CinBaseConfig)
        self.cfg.imeDirName = self.imeDirName
        self.cfg.cinFileList = self.cinFileList
        self.cfg.load()
        self.jsondir = self.cfg.getJsonDir()
        self.cindir = self.cfg.getCinDir()
        self.ignorePrivateUseArea = self.cfg.ignorePrivateUseArea
        self.cinbase.initCinBaseContext(self)

        if not cin_table.curCinType == self.cfg.selCinType and not cin_table.loading:
            loadCinFile = LoadCinTable(self, cin_table)
            loadCinFile.start()
        else:
            if not cin_table.loading:
                self.cin = cin_table.cin
            # if still loading, cbTS.cin is set by checkConfigChange after loading completes

    def initTextServiceExtra(self):
        # 輸入法模組自訂的初始化掛鉤，需要在 initCinBaseContext 前設定的
        # 旗標請覆寫此方法，不要在 __init__ 的 super().__init__() 之後才設定
        pass

    def checkConfigChange(self):
        self.cinbase.checkConfigChange(self, self._cin_table, self._rcin_table, self._hcin_table)

    def onActivate(self):
        TextService.onActivate(self)
        self.cinbase.onActivate(self)

    def onDeactivate(self):
        TextService.onDeactivate(self)
        self.cinbase.onDeactivate(self)

    def filterKeyDown(self, keyEvent):
        return self.cinbase.filterKeyDown(self, keyEvent, self._cin_table, self._rcin_table, self._hcin_table)

    def onKeyDown(self, keyEvent):
        return self.cinbase.onKeyDown(self, keyEvent, self._cin_table, self._rcin_table, self._hcin_table)

    def filterKeyUp(self, keyEvent):
        return self.cinbase.filterKeyUp(self, keyEvent)

    def onKeyUp(self, keyEvent):
        self.cinbase.onKeyUp(self, keyEvent)

    def onPreservedKey(self, guid):
        return self.cinbase.onPreservedKey(self, guid)

    def onCommand(self, commandId, commandType):
        self.cinbase.onCommand(self, commandId, commandType)

    def onMenu(self, buttonId):
        return self.cinbase.onMenu(self, buttonId)

    def onKeyboardStatusChanged(self, opened):
        TextService.onKeyboardStatusChanged(self, opened)
        self.cinbase.onKeyboardStatusChanged(self, opened)

    def onCompositionTerminated(self, forced):
        TextService.onCompositionTerminated(self, forced)
        self.cinbase.onCompositionTerminated(self, forced)

    def onKillFocus(self):
        TextService.onKillFocus(self)
        self.cinbase.onCompositionTerminated(self, True)

    def setCandidatePage(self, page):
        self.currentCandPage = page
