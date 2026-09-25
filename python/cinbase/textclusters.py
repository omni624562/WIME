#! python3
# 把使用者符號檔（symbols.dat、fsymbols.dat、flangs.dat）的內容切成一個個「符號」。
#
# 以前逐碼位切：❤️（❤ + VS16）變成 ❤ 和一個看不見的 VS16 兩個候選字，
# 👍🏻、1️⃣、🇹🇼、👨‍👩‍👧 也都被拆開。這裡只處理符號檔會遇到的情形，
# 不是完整的 Unicode 字素切分：變體選擇符、膚色、ZWJ 連接、鍵帽、國旗
# （兩個區域指示符）與結合用字元都併入前一個符號。

import unicodedata

ZWJ = 0x200D


def _isExtender(ch):
    cp = ord(ch)
    return (0xFE00 <= cp <= 0xFE0F            # 變體選擇符（VS16 讓前一字顯示成彩色 emoji）
            or 0xE0100 <= cp <= 0xE01EF       # 變體選擇符補充
            or 0x1F3FB <= cp <= 0x1F3FF       # 膚色
            or 0xE0020 <= cp <= 0xE007F       # 標籤字元（英格蘭等地區旗）
            or unicodedata.category(ch) in ("Mn", "Me", "Mc"))   # 結合用字元，含鍵帽 U+20E3


def _isRegionalIndicator(ch):
    return 0x1F1E6 <= ord(ch) <= 0x1F1FF


def symbolClusters(text):
    clusters = []
    joinNext = False
    for ch in text:
        if clusters and (joinNext or ord(ch) == ZWJ or _isExtender(ch)):
            clusters[-1] += ch
            joinNext = ord(ch) == ZWJ           # ZWJ 之後那個字也屬於同一個符號
        elif (clusters and _isRegionalIndicator(ch) and len(clusters[-1]) == 1
                and _isRegionalIndicator(clusters[-1])):
            clusters[-1] += ch                  # 兩個區域指示符組成一面國旗
            joinNext = False
        else:
            clusters.append(ch)
            joinNext = False
    return clusters


__all__ = ["symbolClusters"]
