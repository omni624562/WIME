from __future__ import print_function
from __future__ import unicode_literals

from .textclusters import symbolClusters

class symbols(object):

    # TODO check the possiblility if the encoding is not utf-8
    encoding = 'utf-8'

    def __init__(self, fs):

        self.keynames = []
        self.chardefs = {}
        self.leaves = set()
        seen = set()
        categories = set()

        for line in fs:
            # 使用者可編輯的檔案：去掉 UTF-8 BOM（否則第一個分類永遠比對不到），
            # 跳過空行，以及沒有名稱或沒有內容的分類——「名稱=」這種行原本會列進
            # 選單，選到時 getCharDef KeyError，整條管道被重置
            line = line.lstrip('\ufeff').strip()
            if not line:
                continue

            key, root = safeSplit(line)
            key = key.strip()
            if root is None:
                # 一行只放一個符號：放在最上層選單、選了直接送出（設定頁的說明、
                # libchewing 讀同一種檔案都是這樣）。以前當成只含自己的分類，選「…」
                # 「※」還要在只有一項的子頁再選一次
                self.leaves.add(key)
            else:
                root = root.strip()
                if not key or not root:
                    continue
                categories.add(key)
                # 以符號為單位切，不是逐碼位：❤️、👍🏻、🇹🇼 等由多個碼位組成
                for rootstr in symbolClusters(root):
                    try:
                        self.chardefs[key].append(rootstr)
                    except KeyError:
                        self.chardefs[key] = [rootstr]

            if key not in seen:
                seen.add(key)
                self.keynames.append(key)

        # 同名的分類也存在時仍是分類。getCharDef 回傳它自己：組字緩衝模式裡
        # 游標移回這個符號按 ↓ 時，以它列出候選
        self.leaves -= categories
        for key in self.leaves:
            self.chardefs[key] = [key]

    def __del__(self):
        del self.keynames
        del self.chardefs
        self.keynames = []
        self.chardefs = {}

    def isInCharDef(self, key):
        return key in self.chardefs

    def getCharDef(self, key):
        """ 
        will return a list conaining all possible result
        """
        return self.chardefs.get(key, [])

    def getKeyNames(self):
        return self.keynames

    def isLeaf(self, key):
        """key 是直接送出的單一符號（不是分類）。"""
        return key in self.leaves


def safeSplit(line):
    """(分類名稱, 內容)；沒有分隔字元的行回傳 (line, None)。"""
    if '=' in line:
        return line.split('=', 1)
    elif ' ' in line:
        return line.split(' ', 1)
    elif '\t' in line:
        return line.split('\t', 1)
    else:
        return line, None

__all__ = ["symbols"]
