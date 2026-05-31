# WIME 長期效能與介面易用性評估

日期：2026-05-31

本文件整理 WIME 在候選窗新版 UI、大易智慧選字、設定頁改版後的長期效能風險與操作易懂性。評估範圍包含大易/碼表系輸入法、新酷音、PIMETextService、PIMELauncher、設定工具與候選窗呈現。

## 結論

- 目前沒有看到會隨著一般打字時間線性累積、最後必然拖慢輸入的明顯熱路徑。
- 已有幾個重要保護：候選窗 UI 設定避免重複送出、智慧選字資料有上限與寫檔節流、C++ 候選窗樣式 setter 具備 no-op、候選窗更新集中到單次重算。
- 本次評估另外修正幾個長期穩定性與設定易用性風險：
  - RPC pipe 失敗後可重建 overlapped I/O event，避免一次暫時斷線讓同一個 Client 難以恢復。
  - PIMELauncher 背景模式只啟用 warn 以上 tracing，降低每鍵輸入時的 log 處理成本。
  - 大易/碼表系設定工具加上 no-cache 靜態檔、登入後 URL cache-buster、原子寫檔。
  - 大易/碼表系與新酷音設定工具允許把符號/詞庫類內容存成空檔，避免使用者清空欄位後按套用卻沒有作用。

## 長期效能檢查

### 每鍵輸入熱路徑

- `python/textService.py` 會在每個 activated request 執行 `checkConfigChange()`。
- 大易/碼表系與新酷音的設定檔檢查目前有 3 秒節流，不會每鍵讀檔。
- `customizeUI` 原先可能隨候選字更新重送完整候選窗外觀設定；目前大易/碼表系與新酷音都會快取上一組 UI 參數，只在設定改變、啟動或套用設定時重送。
- PIMEClient 的 key-event RPC 已使用較短 timeout 與單次連線嘗試，backend/launcher 暫時不可用時比較不會長時間卡住前景 app。

### 候選窗繪製

- C++ 候選窗的 theme、spacing、key style、message style、stable width、max width setter 已有 no-op，設定未變時不重算。
- `updateCandidates()` 會批次更新 message/header/pageInfo，再重算一次尺寸。
- 每頁候選數仍受選字鍵數與設定限制，候選窗繪製不會因長期使用而無限增加項目。
- 目前可接受的殘留成本：每個候選項目繪製時會建立縮放 key font；在候選數少時影響有限，若未來允許大量候選同頁顯示，可考慮快取縮放字型。

### 智慧選字資料

- `cincount.json` 支援舊格式與壞資料容錯。
- 每個候選字最多保留 32 筆前文上下文，避免長期使用讓單一字的上下文資料無限成長。
- 寫檔有 60 秒節流，離開輸入法時強制保存，避免每次選字都打磁碟。
- 測試 `tests.test_backend_resilience` 已涵蓋資料上限、寫檔節流與壞資料容錯。

### Backend/Launcher 穩定性

- Backend server 單次 request 例外後會回傳 `{"success":false}` 並繼續運作，不會因一筆壞 request 直接退出。
- PIMELauncher 在 client disconnect 時會 unregister client 並送 `{"method":"close"}` 給 backend，避免 backend client map 長期累積。
- 本次修正 PIMEClient RPC event 重建問題：pipe 失敗關閉 event 後，後續重連會重新建立 event。
- 本次修正 PIMELauncher 背景模式 tracing level，避免把大量每鍵 `info!` 事件送進 sink 仍產生不必要處理。

## 設定頁與操作易懂性

### 已符合的方向

- 大易候選窗外觀頁已是所見即所得取向。
- 候選窗配色一次列出所有預覽卡片；實測 DOM 顯示 12 個配色卡片，隱藏 select 不會顯示。
- 選字符樣式一次列出預覽卡片；實測 DOM 顯示 18 個樣式卡片，隱藏欄位只作為儲存值。
- 查無組字提示也用預覽卡片呈現，不再依賴 MessageWindow。
- 主要外觀控制集中在候選窗外觀 toolbar：
  - 使用新版候選窗 UI
  - 固定候選窗最小寬度
  - 自動避開螢幕邊緣
  - 超過最大寬度自動換行
  - 每列候選字數
  - 候選窗字體大小
  - 候選窗最小/最大寬度

### 殘留 UX 風險

- 在窄視窗下，大易設定頁會折疊成漢堡選單，使用者需先展開「一般設定」才看得到「介面外觀」。這是可用的，但發現設定入口的成本仍偏高。
- 候選窗外觀頁在 746x912 視窗下約 2723px 高。一次列出所有預覽符合需求，但頁面長度較長；後續可考慮加上區塊導覽或 sticky 小標題，不建議重新改回下拉選單。
- 樣式名稱多數為英文，符合目前 mockup 討論，但若要讓非技術使用者更快理解，可後續補中文副標或分類。

## 本次驗證

- `python -m py_compile python\cinbase\configtool.py python\input_methods\chewing\config_tool.py`
- `python -m unittest tests.test_backend_resilience`
- `cargo check` in `PIMELauncher`
- `rustfmt --edition 2021 --check src\main.rs`
- `git diff --check` for modified source files
- `cmake --build build --config Release --target PIMETextService`
- `cmake --build build64 --config Release --target PIMETextService`

注意：repo-wide `cargo fmt --check` 目前會因既有檔案格式差異失敗，範圍包含 `PIMELauncher/src/bin/mock_backend.rs`、`PIMELauncher/src/backend_manager.rs`、`PIMELauncher/tests/integration_test.rs`。本次只確認有修改的 `src/main.rs` 格式正確，避免把無關 rustfmt 變更混入。

## 建議的長測清單

- 重開機後第一次啟用大易、新酷音、酷倉，確認候選窗第一次出現就有 header/body。
- 大易輸入多組候選、單一候選、查無組字、翻頁，觀察是否有空白進入實際文件內容。
- 新酷音輸入注音、多候選選字、空白/數字/Enter 行為，確認文字直接送出語意符合原輸入法。
- 開啟設定頁，切換候選窗配色、選字符樣式、提示樣式，套用後立即回到輸入測試。
- 連續打字 30 分鐘以上，觀察候選窗反應、PIMELauncher/Python backend 記憶體、CPU、以及 `cincount.json` 大小。
- 模擬 backend/launcher 暫停或重啟後繼續打字，確認 Client 能恢復連線。
