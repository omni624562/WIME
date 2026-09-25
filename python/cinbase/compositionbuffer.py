#! python3
# 組字編輯緩衝（compositionBufferMode）的唯一擁有者。
#
# 狀態三件組：
#   cbTS.compositionBufferString  目前緩衝字串
#   cbTS.compositionBufferCursor  游標（介於 0..len(string)）
#   cbTS.compositionBufferChar    {字串索引: [型別, 原始組字鍵]}，供 VK_DOWN 重選
#
# 插入、刪除與字元記錄的索引位移一律經過這裡；索引位移必須以排序快照
# 迭代，邊迭代邊改 dict 的 key 會讓新 key 排到迭代尾端被重複位移。


def insertString(cbTS, text, removeStringLength):
    """在游標處插入 text，先取代游標前 removeStringLength 個字。"""
    compPos1 = cbTS.compositionBufferCursor - removeStringLength
    compPos2 = cbTS.compositionBufferCursor - len(cbTS.compositionBufferString)
    if compPos2 < 0:
        cbTS.compositionBufferString = cbTS.compositionBufferString[:compPos1] + text + cbTS.compositionBufferString[compPos2:]
    else:
        cbTS.compositionBufferString = cbTS.compositionBufferString[:compPos1] + text

    cbTS.compositionBufferCursor += len(text) - removeStringLength
    cbTS.setCompositionString(cbTS.compositionBufferString)
    cbTS.setCompositionCursor(cbTS.compositionBufferCursor)


def removeString(cbTS, removeStringLength, removeBefore):
    """自游標前（removeBefore）或游標後刪除 removeStringLength 個字。"""
    # 不可刪超過游標那一側實際有的字數：例如功能選單在緩衝已被清空後退出，
    # 仍會扣掉組字長度，游標變成負數，之後以游標取字就 IndexError
    if removeBefore:
        removeStringLength = max(0, min(removeStringLength, cbTS.compositionBufferCursor))
    else:
        removeStringLength = max(0, min(removeStringLength,
                                        len(cbTS.compositionBufferString) - cbTS.compositionBufferCursor))
    if removeBefore:
        compPos1 = cbTS.compositionBufferCursor - removeStringLength
        compPos2 = cbTS.compositionBufferCursor - len(cbTS.compositionBufferString)
        if compPos2 < 0:
            cbTS.compositionBufferString = cbTS.compositionBufferString[:compPos1] + cbTS.compositionBufferString[compPos2:]
        else:
            cbTS.compositionBufferString = cbTS.compositionBufferString[:compPos1]
        cbTS.compositionBufferCursor -= removeStringLength
    else:
        compPos1 = cbTS.compositionBufferCursor
        compPos2 = cbTS.compositionBufferCursor - len(cbTS.compositionBufferString) + removeStringLength
        if compPos2 < 0:
            cbTS.compositionBufferString = cbTS.compositionBufferString[:compPos1] + cbTS.compositionBufferString[compPos2:]
        else:
            cbTS.compositionBufferString = cbTS.compositionBufferString[:compPos1]

    cbTS.setCompositionString(cbTS.compositionBufferString)
    cbTS.setCompositionCursor(cbTS.compositionBufferCursor)


def recordChar(cbTS, compositionType, compositionChar, compositionCursor):
    """記錄剛插入字元的型別與原始組字鍵；插入點之後的既有記錄右移一格。"""
    if compositionCursor - 1 in cbTS.compositionBufferChar:
        for key in sorted(cbTS.compositionBufferChar.keys(), reverse=True):
            if key >= compositionCursor - 1:
                cbTS.compositionBufferChar[key + 1] = cbTS.compositionBufferChar.pop(key)
    cbTS.compositionBufferChar[compositionCursor - 1] = [compositionType, compositionChar]


def dropCharAt(cbTS, index):
    """刪除 index 處的字元記錄，其後的記錄左移一格（配合字串刪除）。"""
    if index in cbTS.compositionBufferChar:
        del cbTS.compositionBufferChar[index]
    for key in sorted(cbTS.compositionBufferChar.keys()):
        if key > index:
            cbTS.compositionBufferChar[key - 1] = cbTS.compositionBufferChar.pop(key)
