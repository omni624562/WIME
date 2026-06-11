#! python3
# 候選清單分頁的唯一擁有者。
#
# 不變量：每頁候選數不可超過選字鍵數，否則多出來的候選沒有鍵可選，
# C++ 端也會以超出 selKeys 長度的索引取鍵字元（Release 版沒有 assert）。
# 分頁、頁數與上限的計算一律經過這裡，不要在呼叫端重新發明。

import math


def maxCandPerPage(imeDirName):
    """選字鍵數上限：大易候選鍵為「␣'[]-\\」共 6 鍵，其餘輸入法為 1234567890。"""
    return 6 if imeDirName == "chedayi" else 10


def clampCandPerPage(candPerPage, imeDirName):
    return max(1, min(candPerPage, maxCandPerPage(imeDirName)))


def paginate(candidates, perPage):
    """把候選清單切成頁（list of list），行為與舊 list(chunks(...)) 完全一致。"""
    perPage = max(1, perPage)
    return [candidates[i:i + perPage] for i in range(0, len(candidates), perPage)]


def pageCount(total, perPage):
    """總頁數；total 為候選總數。空清單為 0 頁（與舊 math.ceil 行為一致）。"""
    perPage = max(1, perPage)
    return math.ceil(total / perPage)
