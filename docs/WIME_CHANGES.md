# WIME 改名後變更整理

本文件整理自專案參照改為 WIME 後的主要變更。WIME 目前仍沿用多數 PIME 底層名稱與相容路徑，例如 `PIMETextService.dll`、`PIMELauncher.exe`、IPC 訊息前綴、登錄與安裝目錄仍以 PIME 為主；這是為了降低 TSF 註冊、安裝器、既有設定與輸入法模組的破壞性改動。

整理範圍以 `14270dc chore: point project references to WIME` 之後的變更為主，並包含截至 2026-05-31 已實作與驗證的候選窗訊息與效能調整。

## 專案與打包

- 專案對外名稱、GitHub 連結與文件入口改為 WIME。
- 保留 PIME 作為底層相容命名，避免一次性更動 TSF COM 註冊、安裝路徑、Named Pipe、後端協定與既有使用者設定。
- WIME limited installer 目前定位為繁體中文取向版本，僅打包大易、新酷音、新酷倉，並移除簡體輸出轉換、簡體狀態圖示、OpenCC 資料、Rime、拼音與速成。
- 新增限定安裝包建置模式，可只打包大易、新酷音、新酷倉：

  ```powershell
  & 'C:\Program Files (x86)\NSIS\makensis.exe' /DONLY_DAYI_CHEWING_CHECJ installer\installer.nsi
  ```

- 安裝器補強限定版本的輸入法區段與設定捷徑，修正大易與酷倉設定頁無法由選單開啟的問題。

## 簡體中文相關功能移除

- 大易、酷倉、蝦米等 CIN 系輸入法不再提供打繁出簡輸出切換。
- 新酷音不再提供預設輸出簡體中文或 `Ctrl+F12` 繁簡切換。
- 設定頁、語言列選單與 ` 鍵功能選單移除簡體輸出相關入口。
- 舊版設定檔若曾含有 `outputSimpChinese: true` 或 `enableSwitchTCSC: true`，載入與儲存時都會強制視為關閉，避免升級後仍輸出簡體。
- limited installer 排除 `python/opencc`、簡體狀態 icon、簡體安裝語系與不在限定版範圍內的簡體/拼音相關輸入法。
- full installer 與 source tree 內第三方 Rime/OpenCC 資料暫不刪除，作為相容性保留；詳細完成範圍見 `docs/WIME_SIMPLIFIED_CHINESE_REMOVAL.md`。

## 候選窗 UI

- 新增 modern candidate window UI，將舊式白底候選窗重構為雙層結構：
  - header：顯示目前輸入法名稱、組字字根與頁碼。
  - body：顯示候選字或提示訊息。
- 建立規則：候選窗只要出現，就維持 header + body 的雙層視覺結構，不把 body 收成 header-only。
- 大易、酷倉、蝦米的字根移到候選窗 header，不再顯示在實際輸入欄位。
- 新酷音候選窗也接上新版 UI 與相同配置邏輯，修正注音組字、候選字送出、以及設定頁籤切換問題。
- 候選數超過每列顯示數時，header 會顯示 `1/2`、`2/2` 這類翻頁資訊。
- 修正新版候選窗第一次啟動、candidate window 建立時樣式未套用、以及舊樣式殘留的問題。
- 修正候選字貼近下緣、body 過寬、字不完整、選字符與候選字距離不自然等排版問題。
- 淡色系配色調整 header 字根可讀性，避免字根在淺底上看不清楚。
- 被選候選字與選字符會依選取底色自動挑選高對比文字色，避免淡色系或柔和高亮下看不清楚。
- 新增多組候選窗配色與多種選字符樣式，並改成在設定頁一次列出預覽，不再只靠下拉選單。
- header 的輸入法名稱標籤（如「大易」）新增 6 種樣式（2026-06-11）：plain 素色、badge 強調色膠囊（新預設）、accent 強調色文字、tag 描邊標籤、bar 左側色條、underline 底線。顏色全部由目前主題推導，換配色自動跟著走；設定頁「輸入法名稱標籤樣式」以預覽卡片選擇（`candidateHeaderStyle`），mockup 見 `candidate-header-style-mockup.html`。
- 被選候選字的外框與底色改成較柔和的高亮設計，降低視覺壓力。

## 候選窗設定

- 大易、酷倉、蝦米、新酷音逐步補齊候選窗外觀設定。
- 設定頁改為所見即所得取向：
  - 候選窗配色以預覽卡片一次顯示。
  - 選字符樣式以預覽卡片一次顯示。
  - 查無組字訊息樣式與行為以預覽卡片呈現。
- 新增或整理以下設定：
  - 使用新版候選窗 UI。
  - 每列候選字數。
  - 候選窗字體大小。
  - 固定候選窗最小寬度開關與最小寬度數值。
  - 超過最大寬度自動換行與候選窗最大寬度。
  - 自動避開螢幕邊緣。
  - 候選窗配色。
  - 選字符樣式。
  - 查無組字訊息樣式。
  - 查無組字訊息顯示行為。
- 大易、新酷音、新酷倉的新版候選窗 UI 與固定最小寬度已調整為預設啟用方向。

## 查無組字提示

- 不再把 `MessageWindow` 套用成新版候選窗 theme；錯誤與提示改放在候選窗 body。
- `查無組字` 提示改成候選窗內訊息，維持 header/body 結構。
- 新增多種提示樣式，可在設定中切換：
  - Badge：較明確的驚嘆提示。
  - Bar：左側提示線。
  - Dot：低干擾小點提示。
- 新增 progressive 行為：剛組不出字時先用較低干擾樣式，按下確認鍵或空白鍵後再顯示較明確提示。

## 大易與 CIN 系輸入法行為

- 大易字根固定顯示在候選窗 header，這個版本曾以 `字根呈現在候選窗上方` 標記。
- 修復大易選字符在開啟選單後被數字選字鍵污染的問題。
- 修復大易、酷倉設定頁從輸入法選單打不開的問題。
- 補強 `cbTS.cin` 缺失時的防護，避免 filter/onKeyDown 途中例外。
- 修正載入執行緒失敗時 loading flag 未復原的問題。
- 預設設定與使用者設定合併邏輯補強，讓既有使用者也能取得新增設定鍵。

## 大易智慧選字

- 新增大易智慧選字基礎能力。
- 目前採取保守策略，不做激進自動補詞：
  - 近期選字優先。
  - 前一字上下文加權。
- 新增右鍵選單項目與設定欄位，可切換智慧選字、近期優先、上下文加權。
- 智慧選字學習資料保存在 `cincount.json`，並加入容錯處理，能接受舊格式或壞資料。
- 長期使用效能修正：
  - 每個候選字最多保留 32 筆前文上下文。
  - `cincount.json` 寫檔改為 60 秒節流。
  - 離開輸入法時強制保存。
  - 寫檔改用 compact JSON，減少磁碟寫入量。
  - 排序時不再每次完整正規化所有上下文資料。
- 計分改用對數刻度（2026-06-11）：
  - 長期高頻字不再因線性累計永久霸佔前排，「近期選字優先」與「前一字上下文」在計數累積大量後仍有效。
  - 單次誤選不足以跳過既有習慣字，降低候選排序跳動。
  - 上下文加權以 `log2(1+prevCount)*3` 主導，符合「同樣前一字時優先採用慣用字」的預期。

## 新酷音

- 新酷音設定頁籤切換相容性修正。
- 新酷音候選窗外觀設定比照大易補齊。
- 修正注音組字時字根與候選字都被放到 header 的問題。
- 修正新酷音候選字可顯示但送不出、或需要不自然按鍵順序才送出的問題。
- 保留新酷音原本注音組字與選字語意，候選窗 UI 只負責呈現與操作一致性。

## IPC、後端與穩定性

- Python backend 啟動時加入 `PYTHONUNBUFFERED=1`，並讓 server 輸出立即 flush，降低輸入延遲。
- 後端 debug/error 輸出移到 stderr，避免污染 stdout 上的 IPC 協定。
- PIMELauncher Rust 版後端管理修正 mutex 持有時機，減少冷啟動阻塞。
- PIMELauncher 背景模式只啟用 warn 以上 tracing，避免每鍵輸入時仍處理大量 info/debug log 事件。
- PIMEClient pipe read buffer 加大，降低候選清單回傳時的 syscall 次數。
- key-event RPC 連線等待改短，避免 backend 或 launcher 不可用時 UI 長時間卡住。
- PIMEClient 在 pipe 失敗關閉 overlapped I/O event 後會重建 event，避免暫時斷線後同一個 Client 難以恢復。
- JSON 回應處理改用更安全的預設值讀取，避免缺欄位造成 crash。
- `updateCandidateList` 補強欄位缺失防護。
- 候選窗樣式 setter 加入 no-op 檢查，樣式未變時不重算、不重畫。
- `updateCandidates()` 改為批次更新 message/header/pageInfo，最後只重算一次候選窗尺寸。
- 大易/碼表系與新酷音的候選窗 UI 設定加入快取，設定未改變時不再每次候選字更新都重送 `customizeUI`。
- 修正 RPC pipe I/O 逾時後 `CancelIo()` 未等待取消完成就返回，kernel 可能寫入已釋放的堆疊 `OVERLAPPED` 造成宿主應用程式隨機損毀（2026-06-11）。
- 修正 `getPipeName()` 失敗路徑以空指標建構 `std::wstring` 的崩潰風險（2026-06-11）。
- 修正 backend/launcher 不可用時宿主應用程式直接崩潰的問題：RPC 失敗後 `handleRpcResponse()` 仍被呼叫，對 null json 取值會拋出例外並穿過 TSF COM 邊界終止宿主（實測 explorer/conhost 以 ucrtbase 0xc0000409 崩潰）；現在改為 null 防護，且 `updateStatus()` 例外不再外洩（2026-06-11）。
- 候選窗穩定寬度改為跨候選窗重建保留：打字過程收窗再開不會縮回最小寬度造成「時大時小」，焦點離開欄位或寬度設定改變時才重設（2026-06-11）。
- 修正大易候選窗選字符有時顯示 1234567890 的問題：「上次送出的選字鍵」快取原本掛在 CinBase 共享單例上，但實際選字鍵狀態是每個視窗各自的 C++ TextService；多視窗交錯使用時快取誤判已送出，新視窗就停留在 C++ 預設值。快取改為 per-client（2026-06-11）。
- 每頁候選數現在以選字鍵數為硬上限（大易候選鍵 6 個、其餘 10 個）；C++ `updateCandidates()` 同步夾住迴圈上限，Release 版不再可能以超出 `selKeys_` 長度的索引越界取鍵（原本只有會被編譯掉的 assert 保護）（2026-06-11）。
- `CandidateWindow::setCurrentSel()` 對負數游標做防護（2026-06-11）。

## 2026-06-11 效能優化

- 鍵盤事件的 `keyStates` 由 256 元素陣列改為稀疏物件（只送非零鍵），單一鍵事件 payload 由約 900 bytes 降到約 130 bytes；Python/Go 後端同時相容兩種格式，Node 端 JS 索引語意天然相容。
- 候選窗繪製快取：選字鍵縮放字型、面板背景刷、邊框與 header 分隔線畫筆改為跨重繪重用（主題或字型改變時重建），不再每個候選項每次重繪都建立/銷毀 GDI 物件。
- `itemRect()` 改用 `recalculateSize()` 量好的 header 高度，方向鍵移動選取不再每次 `GetWindowDC` 重量。
- 選取移動的重繪改為一次聯集區域且不清背景（`onPaint` 本就覆蓋完整背景），減少重繪與閃爍。
- 修正候選字型更換時 HFONT 被刪除兩次的潛在問題（TextService 與視窗共持同一 handle）。
- `sortByPhrase()` 改用 set 過濾重排（原為 O(n×m) 的 remove/insert），呼叫端以淺拷貝取代 `copy.deepcopy`（每鍵約 20µs → 0.4µs）。
- 大易萬用字元查詢：排序後的字根鍵列表加入快取（表格內容變更時失效）、低頻字去重改用 set、regex 預編譯。
- 修正 8 個碼表系輸入法在等待碼表載入時的 busy-wait 自旋鎖（`while CinTable.loading: continue`）：自旋會佔滿一顆 CPU 核心，且 GIL 競爭反而拖慢載入執行緒；改為 `time.sleep(0.01)` 讓出 GIL。
- 傳統（非 modern）候選 UI 的 `itemRect()` 也改用 `recalculateSize()` 快取的 header 高度，不再每次取 window DC 重量。
- `deploy-test.ps1` 部署清單補上 8 個碼表系 `*_ime.py`。
- MessageWindow 改為重用：同一個視窗 owner 存活期間 `showMessage()` 不再每次重建 HWND；owner 改變、被銷毀或焦點離開時才釋放。
- 候選字字串的文字寬度加入快取（同字型下重複候選不再每次 `GetTextExtentPoint32W`），字型改變時清空，上限 4096 筆。
- `ImeWindow::move()` 在位置與尺寸皆未變時跳過 `MoveWindow`（原本每次候選更新都強制重繪）。
- `cincount.json` 改為先序列化、寫暫存檔再 `os.replace()` 原子取代，中途中斷不再留下半寫入的計數檔。
- 已量測並結案：每鍵的候選分頁 `list(chunks(...))` 實測僅 0.9–3.2µs/次，不值得為 20 個呼叫點引入快取複雜度。

## 2026-06-12 結構性重構（第一階段）

cinbase 神模組開始以 strangler 模式拆分，先抽出兩塊已有測試保護、bug 密度最高的邏輯：

- 新增 `cinbase/selkeys.py`：選字鍵狀態的唯一擁有者。原本散在 4 處的切換邏輯（非大易預設鍵、大易功能選單、大易組字 ×2）與 init 送出收斂為 `initSelKeys` / `applyDefaultSelKeys` / `applyDayiSelKeys`，per-client 快取與「只在變更時送出」的規則只寫一次——「大易選字符變 12345」這類共享狀態 bug 從結構上失去生存空間。
- 新增 `cinbase/pager.py`：候選分頁的唯一擁有者。原本 19 處重複的 `list(self.chunks(...))`、3 處 `math.ceil` 頁數計算、每頁上限 clamp 收斂為 `paginate` / `pageCount` / `clampCandPerPage`，「每頁候選數 ≤ 選字鍵數」的不變量在此集中防守；死碼 `chunks()` 移除。
- 新增 `tests/test_pager.py` 與 selkeys 管理者測試共 19 項，含與舊 `list(chunks(...))` 的全組合等價驗證（total 0–22 × perPage 1–10），確保行為零變化。
- 新增 `cinbase/compositionbuffer.py`：組字編輯緩衝（compositionBufferMode）的唯一擁有者。插入/取代/刪除與字元記錄（`compositionBufferChar`）的索引位移收斂為 `insertString` / `removeString` / `recordChar` / `dropCharAt`；原 CinBase 三個方法改為薄委派，VK_BACK/VK_DELETE 的內聯位移迴圈移除。
- 順手修正潛伏 bug：舊的 BACK/DELETE 位移迴圈**邊迭代邊改 dict 的 key**，新 key 會排到迭代尾端被重複處理，使後方字元記錄一次左移多格（例如索引 5 的記錄在刪除索引 0 後滑到 1 而非 4）；新實作以排序快照迭代，僅左移一格，並有迴歸測試鎖住。
- 新增 `cinbase/menu.py`（功能選單重新設計 + 第三刀抽取）：
  - 候選窗 header 顯示「選單」徽章與麵包屑路徑（如「選單 特殊符號 › 括號」），隨層級即時更新，不再顯示無意義的「大易 `M」。
  - 每個子頁面第一項固定是「↩ 返回」，點選即回上層（與 Backspace 同義）；無上層紀錄時（如 `E 直接進表情符號）返回主選單。
  - 功能開關改為「切換後留在原頁」並即時更新 ☑/☐，連續調整多個開關不再被踢出選單；Esc 關閉。
  - 主選單以使用頻率重排：特殊符號、表情符號、注音符號、外語文字、功能開關、開啟設定視窗…；「開啟設定視窗…」明示其行為與其他子選單不同。
  - 主選單項目與功能開關改以穩定 id 辨識（不再以顯示字串的 index 判斷行為），選單樹、開關清單建構、路徑堆疊集中於 menu 模組。
- 測試總數 74 項（單元）+ 5 項（實機 E2E，含選單麵包屑/返回項回歸）。

## 設定工具可靠性

- 大易/碼表系設定工具補上 no-cache 靜態檔回應與登入後 URL cache-buster，降低更新後設定頁仍讀到舊 HTML/JS 的機率。
- 大易/碼表系設定工具改用暫存檔加 `os.replace()` 原子寫檔，降低套用設定中斷時留下半寫入檔案的風險。
- 大易/碼表系與新酷音設定工具允許符號/詞庫類內容存成空檔，避免使用者清空欄位後按套用卻沒有作用。
- 新增 `docs/WIME_LONG_TERM_EVALUATION.md`，集中整理長期效能、設定頁易用性、已修正風險與長測清單。

## 測試與工具

- 補回 go backend input method 相關測試資料。
- 新增後端韌性測試，涵蓋 malformed request、backend 例外、CIN count 載入容錯、智慧選字資料上限與寫檔節流。
- 新增 `tests/test_selkeys.py`：選字鍵快取 per-client 隔離與每頁候選數上限的單元測試（2026-06-11）。
- 新增 `tests/e2e_pipe_test.py`：直接對 PIMELauncher named pipe 的端對端測試（新酷音打字、大易雙客戶端選字鍵回歸、後端閒置重啟恢復）；未部署環境會自動跳過（2026-06-11）。
- 保留 mockup HTML/SVG 作為候選窗配色、選字符樣式、查無組字提示行為討論與驗證用素材。

## 仍保留 PIME 名稱的地方

以下名稱目前刻意保留，屬於相容層，不代表對外品牌仍是 PIME：

- `PIMETextService.dll`
- `PIMELauncher.exe`
- `PIME_MSG` IPC 訊息前綴
- `C:\Program Files (x86)\PIME`
- `%APPDATA%\PIME`
- `%LOCALAPPDATA%\PIME`
- 多數 C++ namespace、registry key、installer 內部變數

後續若要完整底層改名，需要另外規劃遷移策略，包含既有使用者設定搬移、TSF profile 重新註冊、registry 相容、安裝/解除安裝路徑與舊版清理。
