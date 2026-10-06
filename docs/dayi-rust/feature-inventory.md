# 大易（chedayi）後端功能盤點 — 供 Rust 移植定範圍與差分測試用

分支：`feat/dayi-rust`；盤點日期 2026-10-06。行號以本分支當時的檔案為準（`cinbase/__init__.py` 共 4,123 行）。
路徑簡寫：`CB` = `python/cinbase/__init__.py`、`CFG` = `python/cinbase/config.py`、`TS` = `python/textService.py`、
`IB` = `python/cinbase/ime_base.py`、`DY` = `python/input_methods/chedayi/chedayi_ime.py`、`CIN` = `python/cinbase/cin.py`。

標記：**[大易]** 只有大易會走到；**[共用]** 所有 cinbase 輸入法共用、大易會用到；**[略過]** 大易走不到或不需要；**待確認** 是我沒有實測、只從程式推論的部分。

部分行為以 `tests/cinbase_harness.py`（隔離 APPDATA、攔截 ShellExecuteW / os.startfile）實際打字驗證過，文中標「實測」。

---

## 0. 架構速覽

- 一個 `server.py` 行程服務所有應用程式（client），每個 client 一個 `CheDayiTextService` 實例（`DY:20`），繼承 `CinBaseTextService`（`IB:25`）→ `TextService`（`TS:79`）。
- 真正的邏輯都在模組層單例 `CinBase`（`CB:128`、`CB:3942`），以 `cbTS`（實例）當參數呼叫；狀態幾乎全是掛在實例上的 ~70 個屬性（`CB:143-271`）。
- **跨 client 共用**（同一行程內）：碼表 `CinTable` / 反查 `RCinTable` / 同音 `HCinTable`（`DY:68-92`，大易自己一組）、聯想詞庫 `PhraseData`（`CB:3944`，**所有 cinbase 輸入法共用一份**）、`CinBase.emoji`（模組載入時讀 `data/emoji.json`，`CB:133`）、`Cin._big5_cache`。
- **每個 client 自有**：設定副本 `cfg`（`IB:72` deepcopy）、選字鍵快取 `candselKeys`（`selkeys.py`）、所有組字狀態、資料表物件（swkb/symbols/fsymbols/flangs/userphrase/excludephrase/msymbols/extendtable/dsymbols）。
- 大易子類別只覆寫兩處：`initTextServiceExtra()`（`DY:28-31`，設 `useDayiSymbols=True`）與 `onKeyDown()`（`DY:33-65`，每鍵設 `maxCharLength`、處理大易符號前導字元，再呼叫共用 `onKeyDown`）。其餘大易差異是散在 `CB` 裡的 `imeDirName == "chedayi"` 分支（約 60 行命中）。

---

## 1. 協定介面

### 1.1 傳輸層（`python/server.py`）

- stdin 一行一個請求：`<client_id>|<JSON>`；stdout 回 `PIME_MSG|<client_id>|<JSON>`（`server.py:96-126`）。
- 未知 client_id → 建新 `Client`（`server.py:110-114`）。`method == "close"` → 刪除 client、**不回覆**（`server.py:115-116`）。
- `init`（client 尚無 service 時）：讀 `id`（GUID）、`isWindows8Above`、`isMetroApp`、`isUiLess`、`isConsole`，建立服務；回 `{"seqNum", "success"}`（`server.py:59-84`）。**建立期間塞進 `currentReply` 的欄位不會隨 init 回覆送出**，而是跟著下一個請求（通常 onActivate）一起送出：`setSelKeys:"1234567890"`（`selkeys.py:15-18`）、`changeButton`（`CB:3625` 的 `updateLangButtons`；onActivate 會先 pop 掉，`CB:282`）。
- 任何例外 → `{"success":false}`，並附加寫入 `%LOCALAPPDATA%\PIME\Logs\python_backend.log`（`server.py:42-51,130-140`）。C++ 端收到 success:false 會重置管道（見 `CB:340-345` 註解）。
- JSON：有 orjson 時輸出 UTF-8 不跳脫；否則 `ensure_ascii=False`（`server.py:121-124`）。

### 1.2 請求方法（`TS:101-163`）

每個請求進來時，**若 `isActivated` 為真，先呼叫 `checkConfigChange()`**（`TS:107-108`，見 §5）。之後的回覆 = 累積的 `currentReply` + `return`（若方法回傳非 None）+ `success` + `seqNum`。

| method | 請求欄位 | 處理 | `return` |
|---|---|---|---|
| `filterKeyDown` | KeyEvent | `CB:428-571` | bool：要不要吃這個鍵 |
| `onKeyDown` | KeyEvent | `DY:33` → `CB:1013-2527` | bool（幾乎都 True；空組字時 Enter/Backspace、單獨 Shift 組合鍵回 False） |
| `filterKeyUp` | KeyEvent | `CB:2532-2584` | bool |
| `onKeyUp` | KeyEvent | `CB:2587-2631` | **無**（`IB:128-129` 不回傳，回覆不含 `return`） |
| `onPreservedKey` | `guid`（轉小寫） | `CB:2634-2646` | bool |
| `onCommand` | `id`、`type`（0 左鍵／1 右鍵／2 選單） | `CB:2664-2711` | 無 |
| `onMenu` | `id`（按鈕 id 字串） | `CB:2714-2734` | 選單 JSON 陣列或 None |
| `onCompartmentChanged` | `guid` | 空操作（`TS:194`） | 無 |
| `onKeyboardStatusChanged` | `opened` | `TS:208` 設 `keyboardOpen`，再 `CB:2756-2768` | 無 |
| `onCompositionTerminated` | `forced` | `TS:197`（清 commit/composition 屬性但不寫回覆）再 `CB:2787-2832` | 無 |
| `onKillFocus` | — | `TS:201` 再 `CB.onCompositionTerminated(forced=True)`（`IB:148-150`） | 無 |
| `onActivate` | `isKeyboardOpen` | 設 `isActivated=True`、`keyboardOpen`，`CB:275-325` | 無 |
| `onDeactivate` | — | `CB:392-422` 後設 `isActivated=False` | 無 |
| `ping` | — | 空操作 | 無 |
| 其他 | — | `success:false` | — |

KeyEvent 欄位（`TS:36-76`）：`charCode`、`keyCode`、`repeatCount`、`scanCode`、`isExtended`、`keyStates`（dict `{"vk": state}` 或 256 元素 list；`isKeyDown` = bit 7，`isKeyToggled` = bit 0）。`isPrintableChar` = `charCode > 0x1f && != 0x7f`。

### 1.3 回覆欄位

由 `TS` 的 setter 寫入（`TS:225-316`），另有 cinbase 直接寫 `currentReply[...]` 的擴充欄位：

| 欄位 | 型別 | 語意 | 寫入點 |
|---|---|---|---|
| `compositionString` | str | 組字區字串。**大易一律送 `""`**（字根移到候選窗 header；`CB:2492-2502` 強制覆寫） | `TS:257`；`CB:2501` |
| `compositionCursor` | int | 組字游標；大易同上強制 0 | `TS:261`；`CB:2502` |
| `commitString` | str | 送出文字 | `TS:265` |
| `candidateList` | list[str] | **目前這一頁**的候選（已分頁） | `TS:269` |
| `candidateCursor` | int | 頁內游標 | `TS:273` |
| `showCandidates` | bool | 候選窗顯示 | `TS:277` |
| `setSelKeys` | str | 選字鍵標籤字串；大易 `"␣'[]-\\"`，選單/預設 `"1234567890"` | `TS:281`、`selkeys.py` |
| `openKeyboard` | bool | 要求 C++ 開/關鍵盤（輸入法啟用狀態） | `TS:284` |
| `customizeUI` | dict | 候選窗外觀，見 §1.4 | `TS:296`、`CB:3684-3710` |
| `showMessage` | `{message:str, duration:int=3}` | 提示訊息（實際顯示在候選窗訊息區） | `TS:309` |
| `hideMessage` | true | 收訊息 | `TS:315` |
| `addButton` / `changeButton` | list[dict] | 語言列/系統匣按鈕（`id`、`icon` 絕對路徑、`tooltip`、`commandId`、`type`） | `TS:225-242` |
| `removeButton` | list[str] | | `TS:231` |
| `addPreservedKey` / `removePreservedKey` | list | `{keyCode, modifiers, guid}` / guid | `TS:245-254` |
| `candidateHeader` | str | **擴充**：候選窗標題，大易為 `"大易 " + 字根名稱`（或 `imeDisplayName`）；選單時為 `"選單 路徑 › 子頁"` | `CB:363-388`、`CB:2508-2509`、`CB:1010`、`menu.py:195-198` |
| `candidatePageInfo` | str | **擴充**：`"頁/總頁"`，無則 `""` | `CB:356-361`、`CB:2519-2520` |
| `candidateMessage` | str | **擴充**：`"查無組字"`（顯示在候選窗內） | `CB:3427-3437` |
| `candidateMessageStyle` | str | **擴充**：`"dot"`＝打字中（尚未確認）的低調樣式；確認（按空白/Enter）時移除此欄 | `CB:3430-3436` |

注意：`currentReply` 是 dict，同一請求內多次 setter 以**最後一次為準**（例如 `resetComposition` 先送 `showCandidates:false`，後面又設 True）。差分比對要比「最終回覆」而非呼叫順序。

### 1.4 啟用時一次送出的內容（`CB:275-325`，實測）

onActivate 回覆（假設 Win8+）：

1. `restoreChineseModeOnKeyboardOpen`：鍵盤會開且目前英文、且非 `defaultEnglish` → 切回中文（`CB:2861-2869`）。鍵盤是否會開：Win8+ 時 = `not disableOnStartup`，否則用請求的 `isKeyboardOpen`（`CB:283-286`）。
2. `addPreservedKey`：`{keyCode:32, modifiers:4 (TF_MOD_SHIFT), guid:"{f1dae0fb-8091-44a7-8a0c-3082a1515447}"}`，僅當 `enableShiftSpace`（`CB:2652-2661`）。
3. `addButton`（icon 皆為 `<安裝目錄>\python\cinbase\icons\` 的絕對路徑）：
   - `switch-lang`：`chi.ico`/`eng.ico`，tooltip `中英文切換`，commandId 1
   - `windows-mode-icon`（僅 Win8+）：`{chi|eng}_{full|half}_{capson|capsoff}.ico`，tooltip 例 `大易：中文、半形（按一下切換中英文）`；鍵盤關閉時 `eng_half_capsoff.ico` + `大易：已關閉（按一下或按 Ctrl+空白鍵開啟）`（`CB:2902-2916`），commandId 4
   - `switch-shape`：`full.ico`/`half.ico`，tooltip `全形/半形切換`，commandId 2
   - `settings`：`config.ico`，tooltip `設定`，`type:"menu"`
4. `openKeyboard: not disableOnStartup`（Win8+，`CB:302`）。
5. `customizeUI`（強制送，`CB:325`）。
6. 另外夾帶建立時留下的 `setSelKeys:"1234567890"`。大易的 `"␣'[]-\\"` 要到**第一個組字鍵**的 onKeyDown 才送（實測：第一鍵回覆含 `setSelKeys`）。

`customizeUI` 鍵（`CB:3686-3706`）：`candFontSize`(cfg.fontSize)、`candFontName`(固定 `Microsoft JhengHei`)、`candPerRow`、`candUseCursor`(cfg.cursorCandList)、`candidateLayout`、`candidatePerRow`、`candidateEdgeAvoidance`、`candidatePositionMode`、`candidateOpacity`、`candidateTheme`（`System` 依登錄檔解析成 `Light`/`Graphite`，`candidate_theme.py:57-65`）、`candidateKeyStyle`、`candidateHeaderStyle`、`candidateMessageStyle`、`candidateColors`（舊淺色預設值會被清成 `{}`，`candidate_theme.py:68-84`）、`candidateStyle`、`candidateStableWidth`、`candidateMinWidth`、`candidateWrapToMaxWidth`、`candidateMaxWidth`。之後只在回覆含 `candidateList`/`showCandidates` 且參數有變時才重送（`_lastCandidateUIArgs` 快取，`CB:3707-3710`、`CB:2524-2525`、`CB:2630-2631`）。

onDeactivate（`CB:392-422`）：`removePreservedKey`（若有宣告）、`removeButton` ×4、刪除實例上的資料表、強制存 `cincount.json`。

### 1.5 選單與命令

`onMenu("settings" | "windows-mode-icon")`（`CB:2714-2752`）回傳：

```
[{"text":"中文模式（Shift|左 Shift|右 Shift）","id":1,"checked":中文且鍵盤開},
 {"text":"全形（Shift+空白鍵）","id":2,"checked":全形},  # 括號只在 enableShiftSpace
 {},
 {"text":"參觀 WIME 官方網站(&W)","id":5}, {},
 {"text":"WIME 錯誤回報(&B)","id":6}, {},
 {"text":"設定輸入法模組(&C)","id":3}, {},
 {"text":"網路辭典 (&D)","submenu":[萌典 8, {}, 教育部國語辭典 9, 簡編本 10, 小字典 11, 成語典 12]}]
```

`onCommand`（`CB:2664-2711`）：一律先清 `skipSpaceDeadline`。

| id | 條件 | 動作 |
|---|---|---|
| 1 `ID_SWITCH_LANG` | type 0 或 2 | 放棄組字；type 2 且鍵盤關 → 開鍵盤並設中文；否則切中英 |
| 2 `ID_SWITCH_SHAPE` | type 0 或 2 | 放棄組字、切全半形 |
| 3 `ID_SETTINGS` | 任何 type | **ShellExecuteW** 啟動 `sys.executable configtool.py config chedayi`（SW_HIDE） |
| 4 `ID_MODE_ICON` | 只有 type 0 | 放棄組字；鍵盤關 → 重新開啟；否則切中英 |
| 5 / 6 | | **os.startfile** `https://github.com/omni624562/WIME`（`/issues`） |
| 8–12 | | **os.startfile** 萌典／教育部辭典各網址 |
| 13 `ID_OUTPUT_SIMP_CHINESE` | | 定義了但無處理 **[略過]** |

---

## 2. 碼表與使用者資料

### 2.1 碼表選擇

- `CIN_FILE_LIST = ["thdayi.json", "dayi4.json", "dayi3.json"]`（`DY:23`）；`selCinType` 0＝泰瑞大易四碼、1＝大易四碼、2＝大易三碼（設定頁 `chedayi/config/config.js:3-7`）。
- **出貨預設 `selCinType: 2`（大易三碼）**（`chedayi/config/config.json`）；class 預設是 0（`CFG:132`）。
- 索引超出範圍或型別錯 → 載入 0 號（`tableIndex`，`CB:94-99`；`LoadCinTable` 會把修正後的值寫回 `cfg.selCinType`，`CB:3992`）。
- 最大碼長：`MAX_CHAR_LENGTH = 4`（`DY:22`、`IB:52`），**每個 onKeyDown 開頭**依 `cfg.selCinType` 重設：0/1 → 4、2 → 3（`DY:34-37`）。⚠ 實例建立後到第一個 onKeyDown 之前，三碼也是 4。

| 檔案 | chardefs 數 | keynames | 特色（實測） |
|---|---|---|---|
| `thdayi.json` | 25,165 | 40 個（`,./0-9;a-z`） | 有 `=,`→`，` 等以 `=` 開頭的碼，但 `=` 不在 keynames；`selkey "1234567890"` |
| `dayi4.json` | 16,920 | 40 個 | 無 `=` 碼 |
| `dayi3.json` | 11,695 | 47 個：另有 `'`號 `[`路 `]`街 `-`鄉 `\`鎮 `` ` ``巷 `=`（U+3000） | 最長 3 碼；`privateuse` 47 筆、`dupchardefs` 1,981 筆；`=` 開頭的符號碼（`='`、`=,`…） |

⚠ 三碼的 `'[]-\` 同時是字根與大易選字鍵、`` ` `` 同時是字根與功能選單前導、`=` 同時是字根與大易符號前導，衝突規則見 §4。

### 2.2 碼表 JSON 結構（`python/cinbase/json/*.json`）

由 `build.bat` 呼叫 `python/cinbase/tools/cintojson.py` 從 `python/cinbase/cin/*.cin` 產生，**不進 git**（`tests/cinbase_harness.py:4-6`）。Rust 版要嘛沿用這些 JSON，要嘛自己解析 `.cin`。

```
{ "ename": str, "cname": str, "selkey": str,
  "keynames":   { "<鍵>": "<字根名>" },
  "chardefs":   { "<碼>": ["字", ...] },        // 依 .cin 出現順序；JSON 物件順序有意義
  "privateuse": { "<碼>": ["私用區字", ...] },   // ignorePrivateUseArea 時從 chardefs 移除
  "dupchardefs":{ "<碼>": [...] },               // 載入後未使用
  "cincount":   { "big5F": n, ... } }            // 字集統計，載入時丟棄（CIN:86-88）
```

載入（`CIN:55-104`）：`__dict__.update(data)` → 去私用區 → 建立反向索引 `_char_to_keys`（字 → 碼清單，**依 chardefs 迭代順序**，`CIN:151-158`）→ 讀 `cincount.json`。
`getKeyName` 找不到時回傳鍵本身（`CIN:144-148`）。前綴判斷 `isCharDefPrefix` / `hasLongerCharDefPrefix` 用排序後鍵清單二分搜尋（`CIN:175-204`；Python 字串排序＝碼位序）。

擴充碼表（`userExtendTable`）：`extendtable.dat` 每行 `碼 字`，鍵轉小寫；`priorityExtendTable` 時插在原候選前面，否則附加在後（`CIN:339-357`，`extendtable.py`）。

### 2.3 其他碼表

- 反查（`imeReverseLookup`）：`RCIN_FILE_LIST`（`CFG:78-87`，32 個，`selRCinType` 預設 0＝`checj.json`），`RCin`（`rcin.py`），缺檔記 `fileNotExist`。
- 同音字（`homophoneQuery`）：`["thphonetic.json","CnsPhonetic.json","bpmf.json"]`（`CB:140`），`HCin`（`hcin.py`），`getKeyList` = `sorted(set(...))`。
- 大易符號：`data/dsymbols.json`（`{"chardefs": {單一 ASCII 符號: [候選...]}, "keynames": [...]}`，39 鍵）。
- `` ` `` 符號：`data/msymbols.json`（43 鍵，含 `[]`）。
- 聯想詞庫：`data/phrase.json`（`{"chardefs": {字: [詞...]}, "keynames": [...]}`，3,984 個字頭，`phrase.py`）。
- 表情符號：`data/emoji.json`（5 組 + `modifiercolor`，各有 `*_keynames`）。

### 2.4 使用者資料（皆在 `%APPDATA%\PIME\chedayi\`）

| 檔案 | 讀寫 | 說明 |
|---|---|---|
| `config.json` | 讀；`reLoadTable` 為真時後端會**寫回**（`CB:3885-3889`） | 兩層載入：先套 `input_methods/chedayi/config/config.json`（utf-8-sig）→ normalize → 再套使用者檔（utf-8-sig，失敗改 mbcs）→ 移除退役鍵 → normalize（無效值退回出貨預設）→ `candidateMaxWidth==300` 且無 `candidateMaxWidthMigrated` 時換成 320（`CFG:209-257`）。解析失敗時複製成 `config.json.broken-<mtime>`（`CFG:274-282`）。舊路徑 `~\PIME\chedayi` 存在時整個複製過來（`CFG:231-240`）。寫入用 tmp + fsync + `os.replace`（`CFG:323-340`）。 |
| `cincount.json` | 讀寫 | 選字次數：`{碼: {字: {"count": int, "last": epoch float, "prev": {前一字: int}}}}`，`prev` 最多 32 筆（依次數、字串排序修剪，`CIN:422-434`）；舊格式整數值會正規化。壞檔備份 `cincount.json.broken-<mtime>`（`CIN:385-393`）。寫入 tmp + fsync + replace（`CIN:395-420`）。 |
| `symbols.dat` `swkb.dat` `fsymbols.dat` `flangs.dat` `userphrase.dat` `excludephrase.dat` `extendtable.dat` `msymbols.json` `dsymbols.json` `phrase.json` | 讀 | 先找使用者資料夾，再找 `cinbase/data/`（`CB:3672-3681`、`CFG:354-359`）；`.dat` 解碼 utf-8-sig，失敗改 mbcs（`CB:106-115`）。解析失敗改用內建檔，都失敗給空表。 |

`.dat` 語法：`userphrase`/`excludephrase` 為 `字=詞,詞`（`userphrase.py`）；`symbols`/`flangs` 為 `分類=符號串`，沒有分隔字元的行是「最上層單一符號」（`symbols.py:27-54`）；符號串以 `textclusters.symbolClusters` 切（VS、膚色、ZWJ、鍵帽、國旗、結合字元併入前一個，依 `unicodedata.category`）。`swkb.dat` 鍵轉大寫。

`getConfigDir()` 與 `Cin.getCountDir()` 會 `makedirs` 使用者資料夾（`CFG:195-198`、`CIN:535-538`）。

---

## 3. 設定選項（`CFG:117-183` class 預設；「大易出貨」＝ `chedayi/config/config.json`）

範圍：**大**＝大易專用、**共**＝共用且影響大易、**UI**＝只轉送給 C++ 候選窗、**略**＝大易不需要。

| 鍵 | class 預設 | 大易出貨 | 效果 | 範圍 |
|---|---|---|---|---|
| `selCinType` | 0 | **2** | 碼表 0/1/2；也決定 maxCharLength（`DY:34-37`） | 大 |
| `selDayiSymbolCharType` | 0 | 0 | 大易符號前導：0＝`=`（組字區顯示 `＝`），1＝`'`（顯示 `號`）（`DY:44-45`、`CB:560-566`、`CB:3832-3833`） | 大 |
| `directShowCand` | False | **True** | 打字根即顯示候選；False 時要按空白/↓，且 `autoShowCandWhenMaxChar` 會被設為 True（`DY:63-64`） | 共 |
| `autoCommitSingleCandidate` | False | False | 唯一候選且沒有更長碼時自動送出 + 空白寬限（§4.9） | 共 |
| `supportWildcard` | True | True | 萬用字元查詢 | 共 |
| `selWildcardType` | 0（z） | **1（*）** | 0＝`z`、其他＝`*`（`CB:3805`）；設定頁對大易鎖定不可改（`chedayi/config/config.js:15`）。大易的 `z` 是字根「心」，0 會衝突 | 共（實務固定 `*`） |
| `candMaxItems` | 100 | 100 | 萬用字元結果上限 | 共 |
| `switchPageWithSpace` | False | False | 空白鍵換頁；大易設定頁強制 False 並停用（`config.js:14`），但後端照 config.json 執行 | 共（設定頁鎖） |
| `sortByPhrase` | True | True | 依前一字的聯想詞把候選提前（`CB:3238-3261`） | 共 |
| `showPhrase` | False | False | 送字後顯示聯想字詞清單 | 共 |
| `intelligentSelect` / `…Recent` / `…Context` | True×3 | True×3 | 智慧選字（依前一字預測，§4.12） | 共 |
| `homophoneQuery` | False | （未列，False） | `` ` `` 查同音字；**三碼停用**（`` ` `` 是字根，`menu.py:146-150`、設定頁 `config.js:13`） | 共（三碼略） |
| `selHCinType` | 0 | — | 同音碼表 | 共 |
| `imeReverseLookup` / `selRCinType` | False / 0 | False / — | 送字後顯示該字在反查碼表的字根 | 共 |
| `fullShapeSymbols` | False | False | Shift+符號/數字輸出全形標點（fsymbols） | 共 |
| `directOutFSymbols` | False | False | 全形標點連續輸入時直接送出前一個 | 共 |
| `easySymbolsWithShift` | False | False | Shift+字母輸出 swkb 快速符號 | 共 |
| `directCommitSymbol` | False | **True** | 字根名稱是標點（`，。、；？！`）時直接送出；大易字根名都不是標點，此項只影響 `` ` `` 符號、Ctrl 符號、全形標點的自動送出 | 共（部分） |
| `directOutMSymbols` | True | True | `` ` ``／Ctrl 符號連續輸入 | 共 |
| `outputSmallLetterWithShift` | False | False | 中文模式 Shift+字母輸出小寫（CapsLock 開則大寫） | 共 |
| `defaultEnglish` / `defaultFullSpace` | False | False | 初始中英／全半形（`CB:3618-3625`） | 共 |
| `enableShiftSpace` | True | True | 宣告 Shift+Space 切全半形 | 共 |
| `switchLangWithShift` / `switchLangWithWhichShift` | True / 0 | True / 0 | 單按 Shift 切中英；0 兩邊、1 左、2 右（掃描碼 0x2A/0x36） | 共 |
| `disableOnStartup` | False | — | Win8+ 啟用時送 `openKeyboard:false` | 共 |
| `playSoundWhenNonCand` | False | False | 查無組字時 `winsound.PlaySound('alert')` | 共 |
| `compositionBufferMode` | False | False | 組字編輯緩衝（多字在組字區編輯、↓ 重選）；約 350 行 | 共（可選，建議第二階段） |
| `autoMoveCursorInBrackets` | False | False | 緩衝模式下括號自動把游標放中間 | 共（隨緩衝模式） |
| `userExtendTable` / `priorityExtendTable` / `reLoadTable` | False | False | 擴充碼表；`reLoadTable` 是一次性旗標，後端重載後寫回 False | 共 |
| `ignorePrivateUseArea` | True | — | 去除私用區字（三碼有 47 筆） | 共 |
| `imeDisplayName` | "" | `"大易"` | header 標籤與模式圖示提示的名稱 | 共 |
| `hideComposition` / `hideCompositionLabel` | False / "" | — / `"大易"` | 大易不看這兩個（`forceHeaderComposition` 一律開，`CB:2497`） | 略 |
| `candidatePerRow` | 6 | 6 | 橫排時＝每頁候選數；上限 6（`pager.py:51-57`） | UI＋分頁 |
| `candPerPage` | 9 | 6 | 只在 `candidateLayout=="vertical"` 時用（`CB:3731-3736`） | UI＋分頁 |
| `candidateLayout` | horizontal | horizontal | vertical 時 `candPerRow=1` | UI＋分頁 |
| `fontSize`、`cursorCandList`、`candidateEdgeAvoidance`、`candidatePositionMode`、`candidateOpacity`、`candidateTheme`、`candidateKeyStyle`（固定 word-first）、`candidateHeaderStyle`（固定 accent）、`candidateMessageStyle`、`candidateColors`、`candidateStyle`、`candidateStableWidth`、`candidateMinWidth`、`candidateWrapToMaxWidth`、`candidateMaxWidth`、`candidateMaxWidthMigrated` | 見 `CFG:131-183` | 見出貨檔 | 轉送 `customizeUI`；`isUiLess` 時 `candPerRow=1` | UI |
| `candidateMessageBehavior` | progressive | progressive | progressive 時未確認的「查無組字」帶 `candidateMessageStyle:"dot"` | 共 |
| `candPerRow`（cfg 上的） | 3 | 10 | 後端未使用（`cbTS.candPerRow` 由 candidatePerRow 推得） | 略 |
| `keyboardLayout`、`keyboardType`、`selKeyType` | 0 | 0 | 只有注音／新酷音用；大易 `keyboardLayout` 恆 0 | 略 |
| 退役：`candidateModernStyle`、`messageDurationTime`、`hidePromptMessages` | — | — | 載入時刪除（`CFG:59`） | 略 |

數值範圍檢查（`CFG:37-52`）與型別強制（`CFG:284-318`）也需移植（或至少在 Rust 端讀到壞值時有同樣的退回行為）。

` 功能選單的「功能開關」頁可**暫時**切換（只改實例屬性、不存檔、下次套用設定時被蓋回）：大易提供全部 11 項（`menu.py:97-125`），三碼時拿掉 `homophoneQuery`（`menu.py:156-157`）；執行在 `CB:2929-2952`。

---

## 4. 按鍵行為清單

### 4.1 filterKeyDown：哪些鍵會被吃（`CB:428-571`）

依序判斷：
- [ ] 記錄 `lastKeyDownCode`；`lastKeyDownTime` 只在為 0 時設（`CB:434-436`，供 Shift 切換計時）。
- [ ] 自動送字後的空白寬限中 → True（`CB:438-439`）。
- [ ] 碼表未就緒：組字中或候選窗開 → True；Alt/Ctrl → False；否則中文模式的可見字元 → True（`CB:441-449`）。
- [ ] 只開著聯想字清單（無組字）時按 Alt/Ctrl（Ctrl+符號鍵除外）→ 關清單、回 False（`CB:454-462`）。
- [ ] 組字中或候選窗開 → True；聯想清單開著 → True（`CB:469-473`）。
- [ ] Alt → False；Ctrl → 只有中文模式的 Ctrl 符號鍵（VK 0xBA–0xDF，排除 0xBB `=`、0xBD `-`、0xC0 `` ` ``，`CB:3092-3093`）→ True（`CB:478-491`）。
- [ ] Shift（中文、無 Ctrl）：`easySymbolsWithShift` 且字母、`fullShapeSymbols` 且符號/數字、萬用字元鍵 → True（`CB:494-506`）。
- [ ] 中文模式萬用字元鍵（含數字鍵盤 `*`）→ True（`CB:509-510`）。
- [ ] NumLock 開且 VK_NUMPAD0..VK_DIVIDE → False（`CB:513-518`）。
- [ ] 全形模式：可見字元或空白 → True，其他 False（`CB:521-527`）。
- [ ] 英文半形 → False（`CB:533-536`）。
- [ ] 中文：`charCode.lower()` 是字根 → True；`` ` ``（看 keyStates VK_OEM_3）→ True；大易符號鍵（type 0 看 VK_OEM_PLUS、type 1 看 VK_OEM_7 是否按下）→ True（`CB:546-566`）。
- [ ] 其餘 False。多數 False 分支在訊息顯示中會設 `hideMessageOnKeyUp`。

大易三碼的數字、`'[]-\``=` 都是字根，所以中文模式下全部被吃。

### 4.2 onKeyDown 前置（`DY:33-65`、`CB:1013-1099`）

- [ ] **[大易]** 依 `selCinType` 設 maxCharLength；設 `DayiSymbolChar` / `DayiSymbolString`（每鍵）。
- [ ] **[大易]** 大易符號前導（`DY:47-61`）：中文、選單未開、組字空、非聯想模式、無 Ctrl、`charStr == DayiSymbolChar` → `compositionChar="="`（或 `'`）、`dayisymbolsmode=True`、組字區設 `＝`/`號`。已在符號模式且候選已顯示 → `canUseSelKey=True`；否則若 `dsymbols` 有 `compositionChar[1:]+charStr` → 附加並 `canUseSelKey=False`。（`DY:61` 的 `candidates` 是死碼。）
- [ ] 空白寬限吃掉空白並清除（`CB:1019-1021`）。
- [ ] 碼表未就緒：顯示「正在載入輸入法碼表，請稍候...」或「輸入法碼表載入失敗，請重新安裝 WIME 或檢查碼表檔案」，回 True（`CB:1023-1034`）。
- [ ] NumLock 數字鍵盤（非 `*`）：見 §4.17。
- [ ] 英文模式但仍有組字/候選 → `tempEnglishMode`（只在緩衝模式下有實際效果，`CB:1053-1071`）。
- [ ] 非大易才套用預設選字鍵（`CB:1084-1085`）。
- [ ] 若訊息顯示中 → `hideMessage`（`CB:1097-1099`）。

### 4.3 組字字根與最大碼長

- [ ] 一般模式（`in_normal_input_mode`：選單關、非 multifunction、無 Ctrl、非 ctrl/dayi 符號、非 selcand、非 tempEnglish、非聯想，`CB:1253-1258`）下，字根鍵附加到 `compositionChar`（小寫），組字字串加上字根名（`CB:1416-1428`）。
- [ ] **[大易]** 候選窗已顯示（`showCandidates` 為前一個回覆的狀態）且按的是選字鍵 → **不附加字根**，改當選字（`CB:1397-1399`）。實測：三碼 `a` 後按 `'` 送出第 2 候選「入」，不會變成 `a'`。因為大易組字時 header 契約會一律 `showCandidates:true`（`CB:2518`），**三碼的 `'[]-\` 實際上只能當第一碼**（待確認：是否刻意如此）。
- [ ] 超過 maxCharLength → 去掉最後一碼（`CB:1602-1611`）。實測三碼 `aaaa` 停在 `aaa`。
- [ ] **[大易]** 查無字的字根重新組字：目前組字不是任何碼的前綴、且非萬用字元/特殊模式、無修飾鍵，再按字根 → 丟掉舊字根，從這一鍵重新開始（`CB:1245-1250`、`CB:3404-3425`）。實測 `bl` 後按 `x` → 組字變 `x`。
- [ ] 候選查詢優先序（`CB:1613-1669`）：同音模式 → 碼表 chardefs（`sortByPhrase` → `sortByIntelligentSelect`）→（拼音專用略）→ 全形標點 fsymbols → Ctrl 符號 msymbols → 大易符號 dsymbols（同時把組字區換成第一個符號）→ 萬用字元。

### 4.4 空白／Enter／Esc／Backspace

- [ ] 無組字、選單關、非 multifunction：Enter/Backspace → 回 False 交給應用程式（`CB:1224-1226`）。
- [ ] 單按 Shift＋不可見鍵 → False；但組字中的 Shift+Backspace/Enter/Esc/Delete/方向/Home/End/PgUp/PgDn 照一般鍵處理（`CB:1231-1235`）。
- [ ] 候選顯示中：Space（`switchPageWithSpace` 關）或 Enter → 送出游標所在候選、記錄智慧選字、可能進聯想模式（`CB:2151-2167`）。`canSetCommitString` 為 False 時不送出（例如 `directShowCand` 關時第一下空白只是打開候選窗，`CB:1915-1982`）。
- [ ] Esc：清組字（`CB:1537-1549`）；multifunction 內 Esc 清 `` ` `` 組字（`CB:1167-1172`）；選單內 Esc 關選單（`CB:836-847`）。
- [ ] Backspace：刪最後一碼（以字根名長度裁切組字字串）、游標/頁碼歸零、清萬用字元快取、組字空則 reset（`CB:1552-1599`）；同音模式中先退出同音模式（`CB:1553-1554`）。**[大易]** 大易符號模式的 Backspace：`=x` → 退回 `＝`，`=` → 清空（`CB:1560-1578`）。
- [ ] 沒有候選時按 Space/Enter：**[大易/酷倉/蝦米]** 不是前綴 → 候選窗內 `candidateMessage:"查無組字"`（已確認樣式，無 dot）；是前綴（例如還沒打完）→ `showMessage("查無組字...")`；可能響聲（`CB:2200-2268`）。實測 `b l SPACE`。
- [ ] 打字中組字不是任何碼的前綴：header 模式下送 `candidateMessage:"查無組字"` + `candidateMessageStyle:"dot"`（progressive）與空清單（`CB:2510-2514`）。
- [ ] 組字只有一個符號類字根（`isSymbolsAndNumberChar`）且候選窗沒開時 Enter → 送出組字字串（`CB:2454-2460`）。大易因 header 契約候選窗幾乎總是開著，此路徑大概走不到（待確認）。

### 4.5 選字鍵（大易）

- [ ] 標籤送 C++：`setSelKeys:"␣'[]-\\"`（6 鍵）；後端比對用的 `selKeys` 是 `"'[]-\\"`（`selkeys.py:10-12`）。第 1 候選用空白，`'`＝第 2、`[`＝第 3、`]`＝第 4、`-`＝第 5、`\`＝第 6：`i = selKeys.index(ch) + 1`（`CB:2042-2043`）。
- [ ] 每頁最多 6 個（`pager.clampCandPerPage`，`CB:3736`）。
- [ ] 選字鍵按 Shift 無效（`CB:2040`）；`canUseSelKey` 為 False 時不選（`` ` `` 符號、Ctrl 符號、大易符號延伸期間）。
- [ ] 選字鍵切換只在實際改變時送 `setSelKeys` 並設 `isSelKeysChanged`（per-client 快取，`selkeys.py:21-32`）：進 `` ` `` 選單換 `1234567890`（`CB:754-756`），離開選單／開始一般組字換回大易鍵（`CB:1241-1243`、`CB:1528-1529`）。
- [ ] 選中後：`addIntelligentSelectCount` → `lastCommitString` → `setOutputString`（反查、萬用字元、同音提示）→ `showPhrase` 時進聯想模式 → reset（`CB:2046-2059`）。

### 4.6 換頁與方向鍵（`CB:2080-2121`；選單 `CB:794-835`；聯想 `CB:2325-2366`）

- [ ] ↑：游標 −candPerRow，越界則上一頁游標 0。↓（需 `canSetCommitString`）：+candPerRow，越界則下一頁。←/→：頁內移動，跨頁。Home/End：頁首/頁尾。PgUp/PgDn：換頁、游標 0。
- [ ] 其他鍵（非 Ctrl 符號模式）→ 游標與頁碼歸零（`CB:2191-2194`）。
- [ ] `clampCandidatePosition`：清單變了導致頁碼/游標越界時歸零（`CB:340-354`）。
- [ ] 每次回覆都帶 `candidatePageInfo`（`"n/m"`）。

### 4.7 萬用字元（`CB:1261-1262`、`CB:1646-1669`、`CB:3172-3211`、`CIN:206-323`）

- [ ] 輸入鍵：`*`（charStr）、數字鍵盤 `VK_MULTIPLY`、或 Shift+`8`（keyCode 0x38）（`CB:3183-3195`）；組字字串顯示 `＊`。緩衝模式下超過 maxCharLength 不收。
- [ ] **[大易]** 可變長度：組字恰含一個 `*` 且不在頭尾（如 `a*b`）→ `*` 對應任意長度（regex `(.*)`），否則每個 `*` 對應一碼（`(.)`）、長度固定（`CB:3172-3181`）。
- [ ] 結果排序：先依符合的碼（已排序鍵）的順序收集「高頻字集」（注音、CJK 中可編成 Big5 常用/次常用/符號），去重；達 `candMaxItems` 即停；再接低頻字集（Big5 其他、Ext A–F、相容字、私用區、其他）依字集分組附加（`CIN:271-323`）。字集判斷需要 **Python `big5` 編碼器**（`CIN:545-598`）。
- [ ] 結果再經 `sortByPhrase` 與智慧選字排序（`CB:1667-1669`）。結果有 LRU 快取 32 筆（`CIN:257-269`），實例上另有 `wildcardcandidates` 快取。
- [ ] 選中萬用字元結果 → onKeyUp 顯示該字的字根編碼（`getCharEncode`，例：`仂:　①人力`）（`CB:3471-3478`）。

### 4.8 同音字查詢（`homophoneQuery`，三碼停用）

- [ ] 候選顯示中按 `` ` ``（VK_OEM_3，且 `` ` `` 不是目前碼表的字根）：游標所在字只有一個讀音 → 直接列出同音字；多個讀音 → 先列讀音（`homophoneselpinyinmode`），再用選字鍵/Enter/Space 選讀音（大易索引 +1、跨頁加位移）（`CB:2122-2150`、`CB:2060-2079`、`CB:2168-2182`）。
- [ ] 送出同音字時 onKeyUp 顯示該字在大易碼表的字根（`CB:3499-3504`）。
- [ ] 同音碼表未載入：「同音字碼表檔案不存在！」或「同音字碼表尚在載入中！」。

### 4.9 自動送出唯一候選＋空白寬限

- [ ] 條件（`CB:3263-3276`）：選項開、候選恰 1 個、組字是完整碼、**沒有更長的碼以它開頭**、且不在 selcand/multifunction/tempEnglish/聯想/Ctrl 符號/大易符號/全形標點/同音/萬用字元模式 → 立即送出（`CB:1852-1858`）。
- [ ] 第二條舊路徑（`directShowCand` 開時）：候選 1 個且組字長度 ≥ maxCharLength → 送出（`CB:1984-1994`）。這條**沒有排除萬用字元**，所以萬用字元滿碼且只有一個結果時也會自動送出（待確認是否為預期）。
- [ ] 送出後 `skipSpaceDeadline = time.monotonic() + 1.0`（`AUTO_COMMIT_SPACE_GRACE`，`CB:58`、`CB:3343-3344`）。期限內、中間沒按別的鍵、中文模式、無 Shift/Ctrl/Alt 的下一下空白：filterKeyDown 回 True、onKeyDown 吃掉並清除（`CB:3346-3359`、`CB:1019-1021`）。任何其他鍵、filterKeyUp(空白)、onCommand、onKeyboardStatusChanged、強制終止組字都會清除（`CB:2533-2534`、`CB:2666`、`CB:2757`、`CB:2789`）。

### 4.10 反查（`imeReverseLookup`）

- [ ] 每次送字（`setOutputString`）查反查碼表；有結果且非 UiLess → onKeyUp 顯示（MetroApp 直接在 onKeyDown 顯示）；碼表缺檔/載入中顯示對應訊息（`CB:3480-3497`；`directShowCand` 關的空白路徑另有一份，`CB:1933-1950`）。

### 4.11 聯想字詞（`showPhrase`）與聯想排序（`sortByPhrase`）

- [ ] 來源：`userphrase.dat`（在前）＋內建 `phrase.json`（背景執行緒載入，未載入時只用使用者詞）去重，再扣掉 `excludephrase.dat`（`CB:3213-3236`）。每個按鍵都重算。
- [ ] 送字後 `phrasemode=True`，下一個 onKeyDown 列出 `lastCommitString` 的聯想詞（`CB:2274-2449`）；第一次列出時 `canSetPhraseCommitString=False`，filterKeyUp/onKeyUp 會補送 `showCandidates:true`（`CB:2575-2576`、`CB:2614-2615`）。
- [ ] **[大易]** 選聯想詞用大易選字鍵不加 Shift（索引 +1）；其他輸入法要 Shift+數字（`CB:2302-2322`）。空白選游標所在（`CB:2367-2382`）。實測：`a SPACE` 送「人」並列出聯想，按 `'` 送「士」。
- [ ] 其他鍵：關閉聯想；若是字根（無 Shift）就以它開始新組字（**[大易]** `=`/`'` 是符號前導時進大易符號模式，`CB:2403-2411`），`directShowCand` 時立即列候選；`` ` `` 開始 multifunction；半形可見字元直接送出（`CB:2391-2437`）。
- [ ] `sortByPhrase`：把「前一字的聯想詞」中出現在候選裡的字移到最前面（保持聯想詞順序），其餘照原順序（`CB:3238-3261`）。

### 4.12 智慧選字（依前一字預測）

- [ ] 前一字＝`lastCommitString` 的最後一個字（`CB:3151-3155`）。
- [ ] 分數（`CIN:506-532`）：沒有「同一前一字之後選過」的紀錄 → 0（維持碼表順序）；否則 `3·log2(1+prevCount) + log2(1+count) + (useRecent ? 2/(1+age_days/7) : 0)`，`age_days` 以 `time.time()` 計；依分數降序、同分依原索引（穩定）。`intelligentSelectContext` 關 → 全部 0。
- [ ] 記錄：選字鍵、Enter/Space、自動送出、數字鍵盤送出時 `addCount(碼, 字, 前一字)`；`last=time.time()`（`CIN:492-504`）。
- [ ] `lastCommitString` 清空：強制終止組字/失焦（`CB:2792`）；數字鍵盤輸入後設為該數字（`CB:3319`）。
- [ ] 存檔：每個請求的 `checkConfigChange` 呼叫 `saveCountFile()`，有變更且距上次存檔 ≥60 秒才寫（`CB:3872-3874`、`CIN:20,395-420`）；onDeactivate 與換碼表時強制寫（`CB:421-422`、`CIN:107-116`）。規格測試：`tests/test_smartselect_spec.py`。

### 4.13 大易符號（`=` / `'` 前導，dsymbols）

- [ ] 進入見 §4.2。組字區（header）顯示 `＝`/`號`，之後顯示查到的第一個符號（`CB:1638-1645`、`CB:3369-3377`）。
- [ ] 第二鍵為 dsymbols 的鍵（單一 ASCII 符號/數字，39 個）→ 列出候選。實測（泰瑞四碼與三碼皆同）：`= ,` → `，‘’“”〃…`，空白送 `，`。
- [ ] 符號候選顯示後，`'[]-\` 是選字鍵（`DY:55-56`）。
- [ ] 只打前導字元就按空白/Enter：若目前碼表有 `=`（或 `'`）這個碼 → 用碼表的候選（`CB:1847-1850`）。實測三碼 `'`（type 0 時是一般字根）+空白 → 「號」。
- [ ] ⚠ 因為 `=` 一律先被當符號前導，**泰瑞四碼／三碼表裡 `=` 開頭的碼（`=,` 等）在一般路徑上走不到**，實際用的是 dsymbols（待確認：兩者內容是否相同，影響使用者觀感）。

### 4.14 標點、全形／半形

- [ ] 全形模式：非字根的可見字元在無組字時轉全形送出（`CB:1495-1515`）；英文全形下字根鍵也轉全形（`CB:1383-1392`）。
- [ ] `charCodeToFullshape`：空白→U+3000、ASCII +0xFEE0、非 ASCII 原樣（`CB:3111-3125`）。`SymbolscharCodeToFullshape` 另有特例：`"`→`、`、`'`→`、`、`.`→`。`、`<`→`，`、`>`→`。`、`_`→`－`（`CB:3128-3149`）。
- [ ] Shift+非字根可見字元（中文）：未開 `fullShapeSymbols` → 半形直接送出（字母依 `outputSmallLetterWithShift`/CapsLock），全形模式轉全形；開了 → 有 fsymbols 定義的進全形標點組字，否則轉全形送出（`CB:1435-1492`）。
- [ ] Shift+字根鍵（中文）：萬用字元鍵 → 萬用字元；`easySymbolsWithShift` 且字母 → swkb；`fullShapeSymbols` → fsymbols；否則若是符號/數字字根 → **當字根開始組字**（三碼數字/符號字根），字母 → 送出字母（`CB:1266-1380`）。
- [ ] Shift+Space：preserved key，鍵盤開且 `enableShiftSpace` 時切全半形並回 True（`CB:2634-2646`）；onKeyUp 放棄組字（`CB:2603-2605`）。

### 4.15 Shift／CapsLock／Ctrl／中英切換

- [ ] 單按 Shift 放開：filterKeyUp 判斷 `lastKeyDownCode==VK_SHIFT` 且放開的是 Shift、側別符合設定、且按下到放開 <0.5 秒（`time.time()`）→ `isLangModeChanged`；onKeyUp 切中英並放棄組字（`CB:2536-2554`、`CB:2594-2597`）。側別：掃描碼 0x2A/0x36，否則 `GetAsyncKeyState(VK_LSHIFT/VK_RSHIFT)`（`CB:3453-3457`）。
- [ ] CapsLock 放開：filterKeyUp True、onKeyUp 更新圖示；`capsStates` 由 **`GetKeyState(VK_CAPITAL)`**（讀系統，不是請求的 keyStates）取得（`CB:2557-2558`、`CB:2600-2601`、`CB:2887`、`CB:252`）。
- [ ] Ctrl+符號鍵（中文）：msymbols 符號組字（`_handleCtrlSymbols`，`CB:664-737`）；連按可延伸（如 `[` `]`→`[]`）；`directOutMSymbols` 時換另一組符號會先送出前一個；Enter 送出；**[大易]** `'[]-\` 期間關閉選字鍵（`CB:715-717`）。實測 Ctrl+`;` → `；﹔`，空白送 `；`。
- [ ] 鍵盤開關（Ctrl+Space，`onKeyboardStatusChanged`）：放棄組字、清緩衝、開啟時恢復中文（除非 `defaultEnglish`），更新圖示（`CB:2756-2768`）。
- [ ] `abandonComposition`：清組字、關選單、清 multifunction 與聯想（`CB:2839-2849`）。

### 4.16 `` ` `` 多功能前導與功能選單

- [ ] 中文、選單未開、組字空、按 `` ` `` → `compositionChar="`"`、multifunction（輕鬆輸入法除外；**三碼的 `` ` `` 字根「巷」作第一碼時也走這條**）（`CB:1105-1112`）。
- [ ] 第二鍵：`m`→`` `M ``（功能選單）、`e`→`` `E ``（直接進表情符號）、`u`→`` `U ``（Unicode 輸入）；符號/數字 → msymbols 前綴（**[大易]** `'[]-\` 時關閉選字鍵，`CB:1127-1134`）（`CB:1113-1134`）。
- [ ] 第三鍵：msymbols 延伸；`` `U `` 只收 0-9A-F，最多 6 位；`` ``` `` → 功能選單（`CB:1135-1163`）。實測三碼 `` ``` `` 開出功能選單。
- [ ] `` `U ``+hex+Space/Enter：`unicodeInputCodePoint` 驗證（拒絕 <0x20、0x7F、代理、>0x10FFFF）→ 送出並 onKeyUp 顯示字根；無效 → 「無效的 Unicode 編碼...」；沒打碼 → 「請輸入 Unicode 編碼...」（`CB:2215-2244`、`CB:328-338`）。只有 `` ` `` + Space/Enter → 送出 `` ` ``（`CB:2206-2213`）。
- [ ] multifunction 的 Esc/Backspace/Enter（`CB:1165-1191`）；msymbols 顯示與 `directCommitSymbol`/`directOutMSymbols` 連續輸入（`CB:593-662`、`CB:2027-2036`）。
- [ ] 功能選單（`CB:739-1011`、`menu.py`）：主選單 `特殊符號／表情符號／注音符號／外語文字／功能開關／開啟設定視窗…`；子頁第一項 `↩ 返回`；menutype 0–9（符號分類→子頁、注音、外語分類→子頁、emoji 分類→子分類→字、色調）；選字鍵 `1234567890` 選、Enter/Space 執行、方向/Home/End/PgUp/PgDn 導覽、Backspace／`↩ 返回` 回上層、Esc 關閉；header 為 `選單 路徑 › …`；「開啟設定視窗…」→ **ShellExecuteW** 啟動設定工具（`CB:907-911`、`CB:2920-2928`）；最上層單一符號（symbols/flangs 的 leaf）直接送出。

### 4.17 數字鍵盤（NumLock 開，`CB:1037-1047`、`CB:3282-3338`）

- [ ] 沒在組字：filterKeyDown 放行（應用程式直接收到數字）。
- [ ] 一般組字中：先送出游標所在候選（候選窗沒開時取排序後第一個；查無字則丟棄字根），再接著輸出按下的字元；`lastCommitString` 設成該字元、關聯想。
- [ ] 只開著聯想清單：關清單、回 False。
- [ ] 數字鍵盤 `*` 仍是萬用字元。其他特殊模式（選單、符號）吃掉不處理。規格測試：`tests/test_cinbase_numpad.py`。

### 4.18 放行／忽略的鍵

Alt 組合、非符號 Ctrl 組合、英文半形一切、NumLock 數字鍵盤（未組字）、無組字的 Enter/Backspace、單獨 Shift+不可見鍵（非組字中）都回 False 交給應用程式（§4.1、§4.4）。

### 4.19 訊息（showMessage／onKeyUp 延遲顯示）

即時：`正在載入輸入法碼表，請稍候...`、`輸入法碼表載入失敗，請重新安裝 WIME 或檢查碼表檔案`、`查無組字...`、`沒有候選字...`（緩衝模式 ↓）、`無效的 Unicode 編碼...`、`請輸入 Unicode 編碼...`。
延遲到 onKeyUp（`showMessageOnKeyUp`，`CB:2617-2621`）：字根編碼（萬用字元/同音/Unicode 送字後）、反查結果、`反查字根碼表檔案不存在！`／`…尚在載入中！`、`同音字碼表檔案不存在！`／`…尚在載入中！`。
`isUiLess` 時不顯示；下一個按鍵或 `hideMessageOnKeyUp` 收掉。候選窗內訊息：`candidateMessage:"查無組字"`（§4.4）。

### 4.20 大易的 header 契約（`CB:2490-2522`、`CB:363-388`）

- [ ] 大易／酷倉／蝦米：只要有 header 文字，回覆一律 `compositionString:""`、`compositionCursor:0`、`candidateHeader:"<imeDisplayName 或 大易> <字根名稱串>"`、`showCandidates:true`、`candidatePageInfo` 至少為 `""`；沒有清單時送 `candidateList:[]`，不是前綴則加 `candidateMessage`。功能選單的麵包屑 header 不被覆寫。
- [ ] 字根名稱串：每碼轉 keyname，`*` → `＊`；大易符號模式只有前導時顯示 `＝`/`號`（`CB:3369-3388`）。

### 4.21 組字緩衝模式（`compositionBufferMode`，預設關）

`compositionbuffer.py` 全部、`CB:1672-1789`（←→/Home/End/Backspace/Delete/Esc/Enter/↓ 重選）及散佈在各處的 `if cbTS.compositionBufferMode` 分支（約 214 行命中）。大易使用者可在設定頁開啟。建議 Rust 第一階段先不支援（設定為 True 時退回 Python 或忽略），差分測試分開跑。

### 4.22 onCompositionTerminated／失焦（`CB:2787-2832`）

forced：清空白寬限、清 `lastCommitString`、關選單；非選單且非 `keepComposition` → reset；緩衝模式清緩衝；`keepComposition`（符號連續輸入時送出後保留組字）會依 `keepType` 恢復 `` ` ``／全形標點／Ctrl 符號組字，或重建字根名稱字串。

---

## 5. 差分測試要控制的非決定性

| 來源 | 位置 | 影響 | 控制方式建議 |
|---|---|---|---|
| `time.monotonic()` | `CB:3344`、`CB:3353` | 空白寬限 1.0 秒 | 注入時鐘 |
| `time.time()` | Shift 切換 <0.5 秒（`CB:436`、`CB:2551`）；設定重讀節流 3 秒（`CFG:373`）；碼表重試節流 5 秒（`CB:103`）；`cincount` 的 `last`、`sortByCount` 的新近度衰減（`CIN:499`、`CIN:510-526`）；存檔節流 60 秒（`CIN:398-404`）；系統主題快取 5 秒（`candidate_theme.py:26`） | **候選排序會隨時間改變**（新近度分數） | 注入時鐘；harness 固定 `now` |
| 檔案 mtime | `CFG:371-448`（config.json 與 6 個 .dat 的 mtime 組成 `_version`） | 檔案變了就重讀設定／重建資料表 | 測試期間不改檔，或明確觸發 |
| 背景執行緒 | `LoadPhraseData`（`CB:3665-3667`、`CB:3951-3974`，每個行程第一次建立實例時啟動）；`LoadCinTable`（建立時**同步** `.run()`，`IB:94-97`；設定變更時 `.start()`，`CB:3927-3928`）；`LoadRCinTable`／`LoadHCinTable`（`.start()`，`CB:3903-3911`） | 聯想詞在載入完成前只有使用者詞；反查/同音在載入前顯示「尚在載入中」 | harness 已有 `wait_for_phrase_table()`；Rust 版建議提供「同步載入」模式 |
| Windows API | `GetKeyState(VK_CAPITAL)`（`CB:252`、`CB:2887`，影響模式圖示檔名與 Shift 字母大小寫）；`GetAsyncKeyState`（`CB:3445-3446`，掃描碼不是 0x2A/0x36 時）；登錄檔 `AppsUseLightTheme`（`candidate_theme.py:31-35`，影響 `customizeUI.candidateTheme`） | 回覆內容依機器狀態而變 | 注入或在比對時遮蔽 |
| 聲音 | `winsound.PlaySound('alert', SND_ASYNC)`（`CB:2253`、`CB:2264`） | 副作用 | 攔截 |
| 啟動程式 | `ShellExecuteW`（設定工具）：`onCommand id=3`（`CB:2679-2685`）、`` ` `` 選單「開啟設定視窗…」（`CB:907-908` → `CB:2920-2928`）；`os.startfile`（網址）：`onCommand id=5,6,8,9,10,11,12`（`CB:2696-2711`） | 會開瀏覽器／設定工具 | harness 的 `IsolatedAppData` 已攔截；Rust 版應抽象成可替換的 launcher |
| 檔案寫入 | `cincount.json`（§4.12）；`config.json`（`reLoadTable`）；`*.broken-*` 備份；`makedirs`；舊路徑 copytree；`python_backend.log` | 污染使用者資料 | 隔離 APPDATA/LOCALAPPDATA |
| 共用單例 | `CinTable`/`PhraseData`/`_big5_cache`/`systemThemeCache` 跨 client（`PhraseData` 還跨輸入法） | 測試順序相依 | 每個測試新行程，或明確重設 |
| 亂數 | 無 | — | — |
| Python 語意 | JSON 物件順序（`_char_to_keys` 依 chardefs 順序 → `getKey`、`getCharEncode`）；字串排序（碼位序）；`str.lower()`（Unicode）；`unicodedata.category`（`textclusters.py:20`，依 Python 的 Unicode 版本）；Python `big5` codec（`CIN:557`） | 排序與分組細節 | Rust 用保序 map；Big5 字集建議由 Python 預先產生對照表（WHATWG/encoding_rs 的 Big5 與 Python 不同，待確認差異範圍） |
| 例外 → success:false | 任何未捕捉例外（如 `dsymbols.getCharDef` 缺鍵 KeyError，`dsymbols.py`） | C++ 重置管道 | 差分時 Python 端例外應記為「預期失敗」 |
| 設定副本節流 | 每個實例自己的 `cfg` 3 秒才重讀；`sharedTablesDisagree` 時立即重讀（`CB:3837-3863`） | 多 client 時的重載時機 | 多 client 測試需注意 |

附帶觀察（非移植阻礙，但 Rust 版可順便決定要不要照抄）：`CFG:422-428` 算了 `extendtable.dat` 的 mtime 卻沒放進 `_version`，改擴充碼表不會自動生效（要靠 `reLoadTable`）；`msymbols.json`／`dsymbols.json`／`phrase.json` 的變更也不會被偵測。

---

## 6. 程式量與風險

### 6.1 行數估計（含註解；大易後端相關檔總計約 7,450 行）

| 類別 | 約略行數 | 內容 |
|---|---|---|
| 大易專用 | ~250 | `chedayi_ime.py` 92；`CB` 內 `chedayi` 分支約 60 行命中（含周邊約 120 行）；`selkeys.py` 大易部分；`pager.maxCandPerPage`；`isVariableWildcardQuery`；`dsymbols.py` 49 |
| 酷倉專用 | ~10 | `checj_ime.py` 只有設定類別屬性；`CB` 裡沒有酷倉專屬分支（只出現在 header 標籤清單） |
| 其他輸入法專用（注音/拼音/輕鬆/蝦米鍵盤對映、EndKey、`updateCompositionChar`） | ~90 | `CB` 約 25 行命中＋其區塊，大易走不到 **[略過]** |
| 共用、大易預設會用到 | ~5,300 | 協定/伺服器（`server.py` 156、`serviceManager.py` 92、`textService.py` 316、`keycodes.py` 196）、`CB` 核心（filterKeyDown、onKeyDown 主幹、候選/分頁/選字、符號、選單、聯想、同音、反查、設定套用、載入執行緒）、`cin.py` 601、`config.py` 466、`ime_base.py` 153、資料檔解析器（rcin/hcin/msymbols/symbols/fsymbols/flangs/swkb/phrase/userphrase/extendtable/emoji/textclusters，約 860）、`menu.py` 129、`pager.py` 29、`candidate_theme.py` 91 |
| 共用、預設關（組字緩衝模式） | ~400 | `compositionbuffer.py` 71＋`CB` 內約 214 行命中的分支與 `CB:1672-1789` |
| 不需移植 | — | `debug.py`（只有 DEBUG_MODE）、`configtool.py`（設定工具，非後端）、`DEBUG_MODE` 區塊 |

`cinbase/__init__.py` 非空白非註解 3,306 行；`onKeyDown` 本體 `CB:1013-2527` 約 1,500 行，加上抽出的 `_handleMSymbolsInMultifunctionMode`／`_handleCtrlSymbols`／`_handleMenuMode`（`CB:573-1011`，約 440 行）。

現有可當規格的測試（約 4,500 行）：`tests/test_cinbase_behavior.py`、`test_cinbase_*.py`（config_and_loading、cursor_fuzz、input_leftovers、keystroke_crashes、mode_icon、multi_instance、numpad）、`test_smartselect_spec.py`、`test_selkeys.py`、`test_wildcard_lookup.py`、`test_reverse_lookup.py`、`test_cin_tables.py`、`test_cin_prefix.py`、`test_phrase_data.py`、`test_menu.py`、`test_mode_icon_menu.py`、`test_ime_menus.py`、`test_ime_init_order.py`、`test_pager.py`、`test_compositionbuffer.py`、`test_composition_placeholder.py`、`test_backend_resilience.py`，以及驅動器 `tests/cinbase_harness.py`（可改成同時對 Python 與 Rust 後端送同一串按鍵）。

### 6.2 最容易移植出錯的 10 項

1. **onKeyDown 狀態機**：約 40 個跨按鍵保存的旗標（`multifunctionmode`、`menusymbolsmode`、`ctrlsymbolsmode`、`dayisymbolsmode`、`phrasemode`、`isShowCandidates`、`canUseSelKey`、`canSetCommitString`、`closemenu`、`keepComposition`…），判斷順序相依，且「回覆欄位以最後一次設定為準」（例如 reset 先送 false、header 契約再改 true）。建議 Rust 照區塊順序直譯，先求逐位元一致再重構。
2. **選字鍵與三碼字根衝突**：`'[]-\` 選字（索引 +1）vs 字根、`showCandidates` 取自前一個回覆、`canUseSelKey` 在各模式切換、`setSelKeys` 的 per-client 去重與 `isSelKeysChanged`、選單期間換成 `1234567890`。
3. **大易符號模式**：`DY:47-61` 在共用 onKeyDown 之前先改狀態；`=`/`'` 前導、dsymbols、Backspace 特例、只打前導時改查碼表、聯想模式中的另一條進入路徑（`CB:2403-2411`），以及三碼 `'` 同時是字根「號」。
4. **header 契約與「查無組字」**：`compositionString` 永遠空、`candidateHeader`/`candidatePageInfo`/`candidateMessage`/`candidateMessageStyle:"dot"` 何時出現、`isCompositionCharPrefix` 二分搜尋、查無字根重新組字。
5. **智慧選字與 cincount**：浮點分數、時間衰減、`prev` 修剪規則（依次數再依字串）、舊格式正規化、60 秒存檔節流、壞檔備份、tmp+fsync+replace。
6. **萬用字元**：固定長度 vs 大易可變長度、依已排序鍵收集、高/低頻字集分組（Python `big5` 編碼器）、`candMaxItems` 截斷時機、去重、32 筆 LRU，以及 `directShowCand` 舊路徑對萬用字元的自動送出。
7. **聯想字詞**：每鍵重算、使用者詞＋內建去重＋排除、背景載入未完成時的退化、首次顯示與 onKeyUp 補送 `showCandidates`、大易選字鍵不需 Shift、離開聯想時以該鍵開始新組字。
8. **`` ` `` 功能選單與符號**：10 種 menutype、`prevmenutypelist` 字串編碼（`"type,cursor,page"`）、麵包屑、功能開關的暫時性、`` `U `` 驗證、msymbols 連續輸入與 `keepComposition` 在 onCompositionTerminated 的恢復。
9. **設定載入**：兩層合併、型別強制與範圍、退役鍵、固定值、`candidateMaxWidth` 遷移、ANSI 後備解碼、per-instance 3 秒重讀、`sharedTablesDisagree`、`reLoadTable` 寫回、跨 client 共用碼表的重載與 5 秒失敗重試。
10. **協定細節與時序**：init 不回傳建立時的欄位（延到 onActivate）、onActivate 先 pop `changeButton`、`customizeUI` 快取與系統主題、Shift 單按 0.5 秒計時（從第一次 filterKeyDown 起算）、空白寬限只在 onKeyDown 清除、Win8+ `openKeyboard`/鍵盤關閉時的圖示與選單勾選、CapsLock 讀系統狀態。

其他要留意：組字緩衝模式若要支援，`compositionBufferChar` 的索引位移是另一個高風險區（`compositionbuffer.py:254-269`）；Python 例外導致 `success:false` 的情形 Rust 不必複製，但差分 harness 要能辨識。

---

## 7. 待確認清單

1. 三碼的 `'[]-\` 在候選窗顯示時一律當選字鍵，導致這些字根只能當第一碼——是否為預期行為（`CB:1397-1399`）。
2. 泰瑞四碼／三碼表內 `=` 開頭的碼被大易符號前導遮蔽、改用 dsymbols——兩者內容差異與是否需要保留碼表路徑。
3. `directShowCand` 舊自動送出路徑（`CB:1984`）不排除萬用字元——是否為預期。
4. `CB:2454-2460`（單一符號字根按 Enter 送出）在大易 header 契約下是否還走得到。
5. （已查）三碼與泰瑞四碼的 chardefs 都沒有單碼 `=`，所以 `= SPACE` 沒有候選；三碼有單碼 `'`（號）。`= SPACE` 的實際回覆（查無組字訊息或吃掉）未實測。
6. Python `big5` 與 Rust 可用 Big5 編碼器（encoding_rs/WHATWG）在 CJK 範圍的差異量，決定是否改用預先產生的字集表。
7. `unicodedata` 版本差異對 `symbolClusters` 的實際影響（只影響使用者符號檔中的罕見組合字）。
