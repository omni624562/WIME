# WIME 優化計劃

> 分析基準：master `574c739`（2026-07-05）。
> 本文件為優化機會清單，尚未實作。每項獨立成 commit，完成後在核取方塊打勾並註記 commit。

## 高影響 — 效能熱路徑

### 1. Python：`getCharEncode()` 全表掃描且每次出字跑兩遍
- [x] 完成（`_char_to_keys` 反向索引；呼叫端改單次呼叫）
- 位置：`python/cinbase/cin.py:246-261`；呼叫點 `python/cinbase/__init__.py:1802-1805`、`3124-3127`（另有 `1795`、`2062`、`3117`、`3147`）
- 問題：對整張碼表雙層迴圈 O(N×M)，反查表（RCin）常為數 MB 大表。呼叫端先呼叫一次做 `== ""` 比較、再呼叫一次取值，等於每出一個字全表掃兩遍。
- 做法：Cin 載入時建反向索引 dict（char → [(key, root_index)]），查詢降為 O(1)；呼叫端先存區域變數消除重複呼叫。
- 風險：低（純 Python，可用既有測試驗證）。

### 2. C++：單一按鍵最多 3 次同步 RPC 往返
- [ ] 未實作
- 位置：`libIME2/src/TextService.cpp:717-756`（OnTestKeyDown/OnKeyDown 各打一次 `filterKeyDown` RPC）、`758-790`（KeyUp 同理）；RPC 底層 `PIMETextService/PIMEClient.cpp:859-869`
- 問題：TSF 對同一實體按鍵先送 OnTestKeyDown 再送 OnKeyDown，filter 判斷 RPC 在 UI 執行緒被完整跑兩次；按鍵被吃掉再加一次 onKeyDown RPC，單鍵最多 3 次同步 pipe 來回。
- 做法：以 (wParam, lParam) 或 keyStates 摘要快取上一筆 OnTestKeyDown 的 filter 結果，緊接的 OnKeyDown 重用。注意部分程式不觸發 OnTestKeyDown（程式碼註解已說明），快取 miss 時仍需照常發 RPC。
- 風險：中（動到按鍵熱路徑，需在多種應用程式實測；libIME2 為 submodule，需連動更新指標）。

### 3. Python：`hasLongerCharDefPrefix()` 每鍵全表掃描
- [x] 完成（`_chardef_proper_prefixes` set；`_rebuild_prefix_cache()` 同時建兩份快取）
- 位置：`python/cinbase/cin.py:171-178`；呼叫點 `__init__.py:3004`（shouldAutoCommitSingleCandidate，由 `1721` 每鍵觸發）
- 問題：開啟「自動送出唯一候選字」時每鍵 O(N) 掃描。同檔 `isCharDefPrefix`（143-158）已有 prefix set 快取、`sortedCharDefKeys`（181-190）也有，唯獨這個沒有。
- 做法：重用 `_chardef_prefixes` set，或判斷 `key in prefixes and key not in chardefs`。
- 同類：`isHaveKey`+`getKey`（`cin.py:124-129`）呼叫端慣例是連續掃兩遍全表（`__init__.py:1637-1638`、`1978`、`1993`），可合併為單一函式或用第 1 點的反向索引。
- 風險：低。

## 高影響 — 專案基礎

### 4. backends.json 與實際建置脫節 + go-backend 零 CI 覆蓋
- [x] 完成（移除 node 與 go-backend 條目，僅保留 python 後端）
- 問題：
  - `backends.json` 註冊 `go-backend\server.exe`，但 build.bat 與 CI 都不建置 go-backend，該檔案不存在 → runtime 載入失敗。
  - `backends.json` 仍註冊 `node` 後端，但 build.bat 已註明 node 不再建置。
  - `go-backend/` 有 6 個 `_test.go`（meow/rime/rime_runtime/protocol/server/server_integration），CI 完全沒跑。
- 做法：決定 go-backend 定位——若為主線，納入 build.bat 與 CI（`go build` + `go test ./...`）；若仍為實驗，從 `backends.json` 移除註冊。node 註冊直接移除。
- 風險：低。

### 5. Repo 膨脹止血（pack 已達 121MB）
- [x] 完成（`git rm` rustup-init.exe 與 node_modules；補 .gitignore）
- 問題：
  - `PIMELauncher/rustup-init.exe`（12.8MB）在 HEAD 被追蹤，不該進版控。
  - `node/node.exe` 歷史被提交三次（累積約 44MB）。
  - `node/node_modules/`（emojione，47 個檔）被追蹤。
- 做法（止血，不重寫歷史）：`git rm` rustup-init.exe 與 node_modules，補 `.gitignore`。
- 選配（另議）：`git filter-repo` 清歷史中的 node.exe / python311.dll / 舊字典 / 56000 行 phrase.json 副本——破壞性操作，所有 clone 需重拉，須另行決定。
- 風險：止血低；filter-repo 高（破壞性）。

## 中影響

### 6. 九個 che* 輸入法檔近乎逐字複製貼上
- [ ] 未實作
- 檔案：`python/input_methods/{checj,cheliu,chesimplex,cheez,chearray,chepinyin,chedayi,chephonetic,cheeng}/*_ime.py`
- 問題：checj 對 chesimplex/cheez 只差 12-13 行，差異僅 `imeDirName`、`maxCharLength`、`cinFileList` 三個常數；其餘約 130 行 wrapper + Table 類完全相同。已造成實際漏改：cheliu 缺 `onKillFocus`（checj:139-141 有）。
- 做法：抽 `CinBaseTextService` 基底類別至 cinbase，che* 只宣告常數；chephonetic/chedayi override 專屬邏輯（updateCompositionChar、zhuintab 等）。順帶把 CinTable/RCinTable/HCinTable 單例移到共用模組，讓已載入碼表跨輸入法重用（見第 10 點）。
- 修好後先補 cheliu 的 `onKillFocus`。
- 風險：中（動到全部輸入法的入口，需逐一煙霧測試）。

### 7. C++ 穩定性兩處
- [x] 完成（iconCache_ 加 mutex；compositionCursor clamp 至字串長度）
- 7a. `PIMETextService/PIMELangBarButton.cpp:37`：static `iconCache_` 跨 TSF 執行緒讀寫無鎖（`setIconFile` :80-86、`clearIconCache` :142-147），且 `clearIconCache`（由 `PIMEClient.cpp:325` 解構與 `:813` onDeactivate 觸發）會 DestroyIcon 掉可能仍被其他執行緒引用的 HICON → use-after-free。做法：加鎖 + 改 refcount 或不在單一 profile deactivate 時清全域快取。
- 7b. `PIMETextService/PIMEClient.cpp:573-577`：後端 JSON 傳來的 `compositionCursor` 未驗證即索引 `compositionString[i]`，越界讀取風險。做法：clamp 至 `compositionString.length()`。
- 風險：低（防禦性修正）。

### 8. 候選窗繪製每次重畫建立/銷毀數十個 GDI 物件
- [ ] 未實作
- 位置：`libIME2/src/CandidateWindow.cpp:1002-1254`（paintItem）、`623-684`（訊息列）
- 問題：每個 item、每次 WM_PAINT 都 CreateSolidBrush/CreatePen + DeleteObject（選取項 keycap 樣式一項就 4+ 個）。panel 背景刷/邊框筆/縮放字型已在 :277-308 快取（commit 98e3710），但選取/badge/rail/divider 的顏色物件沒有。
- 做法：依顏色鍵值快取筆刷/筆，比照 panel 物件作法。
- 風險：低。

### 9. 單次 updateStatus 觸發 3+ 次跨行程 GetTextExt
- [ ] 未實作
- 位置：`PIMETextService/PIMEClient.cpp:665-697`（updateStatus 依序跑 updateCandidateList → updateCommitString → updateComposition）；`:511-516`、`:548-553` 各自呼叫 updateCandidatesWindow + updateMessageWindow；`moveCandidateWindow`（`PIMETextService.cpp:414-450`）與 `updateMessageWindow`（`:538-547`）各呼叫 `selectionRect()`（`libIME2/src/TextService.cpp:895-911`，跨行程 GetTextExt）。
- 做法：單次 updateStatus pass 內快取一次 selection rect 共用。
- 風險：低中。

### 10. RCin/HCin 反查表整張常駐記憶體卻只做 O(N) 查詢
- [x] 完成（與第 1 點共用 `_build_reverse_index()`；isHaveKey/getKey 改用 `_char_to_keys`）
- 位置：`python/cinbase/__init__.py:3667`（LoadRCinTable）、`3716`（LoadHCinTable）；碼表 `python/cinbase/json/`（newcj3 6MB、ezbig 5.9MB…）
- 問題：反查/同音只用到 char → 字根對應，卻常駐完整 Cin 物件，且查詢仍是全表掃描。
- 做法：與第 1 點同解——載入時建精簡反向索引 dict，不保留完整 chardefs。建議與第 1 點同一個 commit 系列處理。
- 風險：低。

## 低影響（順手清理）

### 11. 清理已追蹤的 mockup 產物與根目錄雜物
- [x] 完成（`git rm` 5 個 mockup 檔；補 .gitignore；刪 42 個 deploy-test-*.log）
- `git rm`：`candidate-header-style-mockup.html`、`candidate-style-preview.html`、`candidate-window-redesign-mockup.svg`、`candidate-window-ui-mockup.html`、`dayi-interactive-demo.html`
- `.gitignore` 整併零碎規則為 `candidate-*mockup*`、`*-preview.html`、`*-demo.html`
- 工作目錄約 20 個 `deploy-test-*.log` 已被 ignore，直接刪除即可。

### 12. CMake 最低版本過舊
- [ ] 未實作
- `CMakeLists.txt:1` 為 `cmake_minimum_required(VERSION 2.8.11)`（2013 年），導致 build.bat 每個 cmake 呼叫都塞 `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` workaround。提升最低版本後移除 hack。

### 13. KeyEvent 每事件重建 256 元素陣列
- [ ] 未實作
- `python/textService.py:46-61`：keyStates 稀疏 dict 傳入時每事件配置 `[0]*256` 回填；一次實體按鍵建 4 個 KeyEvent。改 `isKeyDown`/`isKeyToggled` 用 `self.keyStates.get(code, 0)` 直查稀疏 dict。

### 14. onKeyDown 巨型方法持續分解
- [ ] 未實作
- `python/cinbase/__init__.py:502` 起約 1050+ 行。同組旗標判斷在 `1146`、`1149`、`1317` 幾乎逐字重複；`cin.isInKeyName(charStrLow)` 同路徑多次呼叫。
- 做法：方法開頭把純函式結果算一次存區域變數；msymbols/ctrlsymbols 分支抽方法（延續已拆 menu/pager/selkeys 的方向）。另外 `687-690`、`736-745`、`1092-1101`、`1124-1133` 的「送出候選回填 compositionBufferChar」區塊重複 4+ 次，抽成單一輔助方法，迴圈用 `enumerate` 取代 `.index()`（重複字元會取錯位置）。

### 15. 其他小項
- [ ] 未實作
- `cin.py:457-506` `getCharSet`：`charsetRange` 提升為 class 常數、`in range(...)` 改比較運算、big5 編碼結果快取（僅萬用字元查詢路徑）。
- `phrase.py:34` `getCharDef` 用 `self.chardefs[key]`（KeyError）與 `cin.py:140` 的 `.get(key, [])` 語意不一致，統一。
- `libIME2/src/TextService.cpp:146-168` `isInsertionAllowed` 算出 `allowed` 卻恆 `return false`——死碼/潛在 bug，目前無實害，處理時留意。
- `PIMETextService/PIMETextService.cpp:535` `SetTimer(..., duration * 1000, ...)` 後端傳入值未做上限，極端值溢位。

## 建議執行順序

1. **第 1 + 3 + 10 點**（Python 反向索引 + prefix 快取）：純 Python、風險低、每鍵受益，先做。
2. **第 4 點**（backends.json 對齊 + CI 補 go test）：修現在就會踩到的 runtime 失敗。
3. **第 5 點止血 + 第 11 點**（repo 清理）：機械性低風險。
4. **第 7 點**（C++ 防禦性修正）。
5. **第 2 + 8 + 9 點**（C++ 熱路徑）：效益大但需實測驗證，留到有完整測試時間再做。
6. **第 6 點**（che* 基底類別）：影響面廣，單獨一個系列處理。

## 附註

- 已確認做得不錯、不需再動：`config.update()` 3 秒節流、`saveCountFile` 60 秒 + dirty flag、`sortByPhrase` set 化、`sortedCharDefKeys` 快取、`ImeWindow::move` 位置不變 early-return、訊息視窗重用、RPC 崩潰防護（b1b725e）。
- `PIMEClient.cpp:1250-1259` `isPipeCreatedByPIMEServer` 恆回傳 true（pipe 對端驗證未實作，原始碼有 FIXME）——安全面既有缺口，不在本次優化範圍，記錄備查。
- libIME2 為 git submodule，改動需在 submodule repo 內 commit 後更新主 repo 指標。
