#! python3
# 選字鍵狀態的唯一擁有者。
#
# 「上次送出的選字鍵」是 per-client 狀態（每個應用程式視窗各有自己的
# C++ TextService），曾因快取放在共享單例上造成大易選字符停留在
# 1234567890。所有切換一律經過這裡，避免同樣的 bug 再寫出來。

DEFAULT_SELKEYS = "1234567890"

# 大易候選鍵：空白鍵選第 1 個候選，'[]-\ 選第 2~6 個
DAYI_DISPLAY_SELKEYS = "'[]-\\"
DAYI_CAND_SELKEYS = "␣'[]-\\"


def initSelKeys(cbTS):
    """Client 建立時呼叫：設定 per-client 快取並送出預設選字鍵。"""
    cbTS.candselKeys = DEFAULT_SELKEYS
    cbTS.TextService.setSelKeys(cbTS, cbTS.candselKeys)


def applySelKeys(cbTS, displayKeys, candselKeys):
    """切換選字鍵；只在實際變更時才送 setSelKeys 給 C++ 端。

    回傳是否有送出（呼叫端可據此補做額外狀態，如 isShowCandidates）。
    """
    cbTS.selKeys = displayKeys
    if cbTS.candselKeys == candselKeys:
        return False
    cbTS.candselKeys = candselKeys
    cbTS.TextService.setSelKeys(cbTS, candselKeys)
    cbTS.isSelKeysChanged = True
    return True


def applyDefaultSelKeys(cbTS):
    return applySelKeys(cbTS, DEFAULT_SELKEYS, DEFAULT_SELKEYS)


def applyDayiSelKeys(cbTS):
    return applySelKeys(cbTS, DAYI_DISPLAY_SELKEYS, DAYI_CAND_SELKEYS)
