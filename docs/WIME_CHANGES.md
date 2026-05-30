# WIME 改名後變更整理

本文件整理自專案參照改為 WIME 後的主要變更。WIME 目前仍沿用多數 PIME 底層名稱與相容路徑，例如 `PIMETextService.dll`、`PIMELauncher.exe`、IPC 訊息前綴、登錄與安裝目錄仍以 PIME 為主；這是為了降低 TSF 註冊、安裝器、既有設定與輸入法模組的破壞性改動。

整理範圍以 `14270dc chore: point project references to WIME` 之後的變更為主，並包含截至 2026-05-31 已實作與驗證的候選窗訊息與效能調整。

## 專案與打包

- 專案對外名稱、GitHub 連結與文件入口改為 WIME。
- 保留 PIME 作為底層相容命名，避免一次性更動 TSF COM 註冊、安裝路徑、Named Pipe、後端協定與既有使用者設定。
- 新增限定安裝包建置模式，可只打包大易、新酷音、新酷倉：

  ```powershell
  & 'C:\Program Files (x86)\NSIS\makensis.exe' /DONLY_DAYI_CHEWING_CHECJ installer\installer.nsi
  ```

- 安裝器補強限定版本的輸入法區段與設定捷徑，修正大易與酷倉設定頁無法由選單開啟的問題。

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
- 新增多組候選窗配色與多種選字符樣式，並改成在設定頁一次列出預覽，不再只靠下拉選單。
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
- PIMEClient pipe read buffer 加大，降低候選清單回傳時的 syscall 次數。
- key-event RPC 連線等待改短，避免 backend 或 launcher 不可用時 UI 長時間卡住。
- JSON 回應處理改用更安全的預設值讀取，避免缺欄位造成 crash。
- `updateCandidateList` 補強欄位缺失防護。
- 候選窗樣式 setter 加入 no-op 檢查，樣式未變時不重算、不重畫。
- `updateCandidates()` 改為批次更新 message/header/pageInfo，最後只重算一次候選窗尺寸。

## 測試與工具

- 補回 go backend input method 相關測試資料。
- 新增後端韌性測試，涵蓋 malformed request、backend 例外、CIN count 載入容錯、智慧選字資料上限與寫檔節流。
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
