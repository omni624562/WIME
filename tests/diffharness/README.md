# 差異測試框架（diffharness）

用來證明另一套後端（例如 Rust 版大易）對每個請求的回覆都和現在的 Python 後端**完全一樣**。

框架只透過啟動器的 stdio 協定和後端溝通，不在意後端用什麼語言寫：

- 輸入：`<client_id>|<json>`
- 輸出：`PIME_MSG|<client_id>|<json>`

## 組成

| 檔案 | 用途 |
|---|---|
| `driver.py` | 啟動後端、送按鍵與請求、錄下回覆、比對兩份錄音 |
| `keys.py` | 按鍵事件，格式和 `PIMEClient.cpp` 送出的一樣（稀疏的 `keyStates`、Shift 左右掃描碼） |
| `py_reference_backend.py` | 基準後端：`server.py` 加上下面的「測試約定」 |
| `suites/*.json` | 手寫的情境 |
| `golden/*.jsonl` | Python 後端對各情境的標準答案 |

## 讓結果每次都一樣

基準後端只改會讓兩次執行結果不同的地方：

- **虛擬時鐘**：每個請求前進 0.01 秒，情境裡的 `{"wait": 秒數}` 會讓時鐘多走。像是「自動送出後 1 秒內的空白鍵忽略」這類跟時間有關的行為，才測得準。
- **碼表同步載入**：第一個按鍵就看得到完整碼表。
- **不啟動任何程式**：設定工具、網頁、音效都改成記錄下來。回覆裡會多出 `_testLaunches` 或 `_testSounds` 欄位。
- **固定機器狀態**：Caps Lock 關、沒有實體按鍵被按住、Windows 用淺色主題。
- **每次都用暫存的 APPDATA**：不會讀寫使用者真正的設定和詞頻。

### 新酷音（chewing）另外固定的地方

新酷音的前端 `input_methods/chewing/chewing_ime.py` 在第一個新酷音用戶端建立時才載入，基準後端在載入後立刻換掉：

- **虛擬時鐘**：Shift 單按（< 0.5 秒）用的 `time.time()`、設定檔每 3 秒檢查一次用的 `time.monotonic()` 都改看虛擬時鐘。
- **機器狀態**：Caps Lock 關（`getCapslockState`）、沒有實體按鍵按住（`isPressed`）、淺色主題。
- **候選窗一列幾個字**（上下鍵的步幅）：`candidate_layout.py` 本來用 GDI 量字寬，結果隨字型和 DPI 而不同，golden 在別台電腦（CI 的英文 Windows）會對不上。測試時兩邊都改用同一個固定模型：DPI 96，碼位 ≥ U+1100 的字寬一個 em（`MulDiv(字級, 96, 72)` px），其他半個 em。設 `WIME_TEST_GDI=1` 則保留真的 GDI 量測（DPI 仍固定 96），用來比對兩邊的 GDI 實作。
- **使用者詞庫**：每組情境一個新的暫存 APPDATA，所以 `chewing.dat` 一開始是空的；同一組情境裡學到的詞會留給後面的情境，這也是比對的一部分。
- 情境檔可以用 `"files"` 預先放檔案到 `%APPDATA%\PIME\<ime>`（例如自訂的 `symbols.dat`、舊版的 `chewing.sqlite3`），測試設定檔整理和舊詞庫轉換。

## 其他後端要遵守的測試約定

環境變數 `WIME_TEST_MODE=1` 時：

1. 支援 `{"method": "__advanceClock", "seconds": s}` 請求，用虛擬時鐘取代真實時間。
2. 不啟動程式，也不發出聲音。要啟動或發聲時，在該次回覆加上 `_testLaunches: [[種類, 檔名]]`（種類是 `ShellExecuteW` 或 `startfile`）或 `_testSounds`。
3. 碼表在回覆第一個請求前就載入完成。
4. 新酷音：GetKeyState／GetAsyncKeyState 一律當成沒按、主題是淺色，候選窗字寬用上面的固定模型（除非 `WIME_TEST_GDI=1`）。

比對前，圖示路徑一律只比檔名，因為每套後端的安裝位置不同。

## 用法

```bash
python tests/diffharness/driver.py gen out.json --seed 1 --count 50 --length 80   # 產生隨機情境（--ime chewing：新酷音的按鍵）
python tests/diffharness/driver.py record suite.json golden.jsonl                 # 錄下 Python 後端的回覆
python tests/diffharness/driver.py compare suite.json golden.jsonl --backend "path\to\backend.exe"
python tests/diffharness/driver.py diff suite.json --backend "path\to\backend.exe"  # 直接和 Python 後端並排比
```

`tests/test_diffharness.py` 會檢查三件事：Python 基準後端每次的結果都一樣、虛擬時鐘有效、`golden/` 還和目前的 Python 後端一致。

改了 Python 後端的行為之後，要重新錄製 golden，並在 PR 裡說明差異。
