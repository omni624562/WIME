#! python3
# 功能選單（``` 進入）的選單樹與導航狀態的唯一擁有者。
#
# 設計原則：
#   - 主選單項目以穩定 id 辨識，不再以顯示字串的 index 判斷行為。
#   - 每個子頁面第一項固定是「↩ 返回」，不必記 Backspace 也能回上層。
#   - cbTS.menupathlist 記錄目前所在路徑，候選窗 header 顯示
#     「選單 路徑 › 子頁」麵包屑（「選單」吃 header 標籤樣式）。

BACK_ITEM = "↩ 返回"

MAIN_MENU = [
    ("symbols", "特殊符號"),
    ("emoji", "表情符號"),
    ("bopomofo", "注音符號"),
    ("flangs", "外語文字"),
    ("toggles", "功能開關"),
    ("settings", "開啟設定視窗…"),
]

_MAIN_MENU_IDS = {label: itemId for itemId, label in MAIN_MENU}

# 功能開關頁的麵包屑。開關只改目前這個程式的狀態、不會存檔，存任何設定後也會
# 回到設定值（help.htm 有寫，頁面上以前沒有），標題要直接講清楚
TOGGLES_PAGE_TITLE = "功能開關（暫時，只影響這個程式）"

# 功能開關定義：屬性名 → 顯示文字
TOGGLE_DEFS = [
    ("fullShapeSymbols", "Shift 輸入全形標點"),
    ("easySymbolsWithShift", "Shift 快速輸入符號"),
    ("playSoundWhenNonCand", "拆錯字碼時發出警告嗶聲提示"),
    ("showPhrase", "輸出字串後顯示聯想字詞"),
    ("sortByPhrase", "優先以聯想字詞排序候選清單"),
    # 智慧選字只看前一個字：在同一個前一字之後選過的字才會提前，沒有紀錄時維持
    # 碼表順序；「近期」只在這些字之間比先後（cin.sortByCount）。以前寫成
    # 「智慧選字」「近期選字優先」，像是常用、最近選的字都會往前排
    ("intelligentSelect", "智慧選字（依前一字排序）"),
    ("intelligentSelectRecent", "智慧選字：前一字相同時近期優先"),
    ("intelligentSelectContext", "智慧選字：參考前一字"),
    ("supportWildcard", "萬用字元查詢"),
    ("imeReverseLookup", "反查輸入字根"),
    ("homophoneQuery", "同音字查詢"),
]

_ALL_TOGGLES = [attr for attr, _ in TOGGLE_DEFS]

# 各輸入法提供的開關（沿用原本的清單）
TOGGLES_BY_IME = {
    "chephonetic": ["fullShapeSymbols", "easySymbolsWithShift",
                    "playSoundWhenNonCand", "showPhrase", "sortByPhrase",
                    "imeReverseLookup", "homophoneQuery"],
    "cheez": ["playSoundWhenNonCand", "showPhrase",
              "sortByPhrase", "supportWildcard", "imeReverseLookup"],
    "chearray": _ALL_TOGGLES,
    "chedayi": _ALL_TOGGLES,
}

_DEFAULT_TOGGLES = ["fullShapeSymbols", "easySymbolsWithShift",
                    "playSoundWhenNonCand", "showPhrase", "sortByPhrase",
                    "supportWildcard", "imeReverseLookup", "homophoneQuery"]

_TOGGLE_LABELS = dict(TOGGLE_DEFS)


def mainMenuLabels():
    return [label for _, label in MAIN_MENU]


def mainMenuId(label):
    return _MAIN_MENU_IDS.get(label)


def toggleAttrsFor(imeDirName):
    return list(TOGGLES_BY_IME.get(imeDirName, _DEFAULT_TOGGLES))


def homophoneKeyIsRoot(cbTS):
    """` 是目前碼表的字根（大易三碼的「巷」）時，同音字查詢用的 ` 鍵會先被當成字根，
    只有打滿碼之後才查得到，所以整個功能停用。"""
    cin = getattr(cbTS, "cin", None)
    return cin is not None and cin.isInKeyName("`")


def buildToggleItems(cbTS):
    """回傳 (顯示清單, 屬性清單)；顯示清單帶目前 ☑/☐ 狀態。"""
    attrs = toggleAttrsFor(getattr(cbTS, "imeDirName", ""))
    if "homophoneQuery" in attrs and homophoneKeyIsRoot(cbTS):
        attrs.remove("homophoneQuery")
    labels = []
    for attr in attrs:
        mark = "☑" if getattr(cbTS, attr, False) else "☐"
        labels.append(mark + " " + _TOGGLE_LABELS[attr])
    return labels, attrs


def toggleIndex(labels, itemName):
    """功能開關項目 -> buildToggleItems 的索引；找不到回 None。
    以 ☑/☐ 之後的文字比對：清單顯示後，設定可能已在設定頁被改掉（☐ 變 ☑），
    直接用整個字串 index() 會丟 ValueError。"""
    names = [label[2:] for label in labels]
    name = itemName[2:]
    return names.index(name) if name in names else None


def withBack(items):
    """子頁面候選清單：固定以「↩ 返回」開頭。"""
    return [BACK_ITEM] + list(items)


def resetPath(cbTS):
    cbTS.menupathlist = []


def pushPath(cbTS, name):
    if not hasattr(cbTS, "menupathlist"):
        cbTS.menupathlist = []
    cbTS.menupathlist.append(name)


def popPath(cbTS):
    path = getattr(cbTS, "menupathlist", [])
    if path:
        path.pop()


def headerText(cbTS):
    """候選窗 header 麵包屑；第一個詞「選單」會套 header 標籤樣式。"""
    path = getattr(cbTS, "menupathlist", [])
    return "選單 " + (" › ".join(path) if path else "功能選單")
