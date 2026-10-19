# 模糊測試（fuzzing）

用 [cargo-fuzz](https://github.com/rust-fuzz/cargo-fuzz)（libFuzzer，覆蓋率導向）餵大量變形的輸入給 WIME 處理外部資料的地方，找出會 panic、讓請求失敗或卡住的情況。

## 目標

cinbase-rs（`src/fuzz.rs`，每個目標一個函式，`fuzz/fuzz_targets/*.rs` 只是包一層）：

| 目標 | 測什麼 |
|---|---|
| `backend` | 一個 TSF 用戶端的完整生命週期：init、onActivate、按鍵（filterKeyDown → onKeyDown → …，照 DLL 的順序）、選單與命令、切換鍵盤（照 DLL 的作法：關閉後重新 init）。輸入的第一個位元組選大易／酷倉／新酷音。每個請求都必須成功，回覆欄位的型別必須是 DLL 預期的 |
| `backend_raw` | 任意的 `<client_id>\|<json>` 請求行（任何本機程式都能透過管道送）：可以失敗，不能 panic |
| `config_http` | 設定工具的 HTTP 伺服器（任何本機程式都能連）：原始位元組直接進 `handle_one_request`，第一個位元組選大易／酷倉／新酷音。種子帶有登入 cookie，所以會走到需要登入的 API（存設定、使用者詞庫、匯入詞庫檔） |
| `multipart` | 上傳檔案的 multipart/form-data 解析 |
| `http_fields` | Cookie、查詢字串、百分比編碼 |
| `json_body` | 設定頁送來的 JSON：讀進來、寫回去要一模一樣（找到過 serde_json 浮點數讀取差一位元的問題） |
| `user_dictionary` | 匯入的新酷音使用者詞庫（chewing.dat 或舊的 chewing.sqlite3），經過 libchewing |

PIMELauncher（`PIMELauncher/src/fuzz.rs`）：

| 目標 | 測什麼 |
|---|---|
| `lines` | 啟動器讀後端輸出的分行方式（`LossyLinesCodec`）：不論位元組怎麼分段送到，切出來的行都一樣；過長或不是 UTF-8 的行被丟掉，不會讓整個讀取停掉 |

## 每次 CI 都會跑的部分

`fuzz/seeds/<目標>/`（手寫的種子）和 `fuzz/regressions/<目標>/`（找到過問題的輸入）會由一般的 `cargo test`（stable）重播一次：`tests/fuzz_corpus.rs`。不需要 nightly。

種子由 `fuzz/make_seeds.py` 產生（要先 `cargo build --release`，它會用 repo 的 wime-config.exe 在暫存設定檔裡做出真的 chewing.dat）：

```
python\python3\python.exe cinbase-rs\fuzz\make_seeds.py
```

## 自己跑

需要 nightly 和 cargo-fuzz（一次就好）：

```
rustup toolchain install nightly --profile minimal
cargo install cargo-fuzz --locked
```

Windows 上 ASan 的執行階段 DLL 要在 PATH 裡（否則程式一啟動就是 `STATUS_DLL_NOT_FOUND`），在 Visual Studio 的 `VC\Tools\MSVC\<版本>\bin\Hostx64\x64`。大易、酷倉的碼表要先產生（`build.bat` 或 `python\python3\python.exe python\cinbase\tools\cintojson.py`）。

```
cd cinbase-rs
cargo +nightly fuzz run -O backend fuzz/corpus/backend fuzz/seeds/backend -- -max_total_time=600
```

- 找到問題時 libFuzzer 把輸入存在 `fuzz/artifacts/<目標>/crash-*`。重跑一次：`cargo +nightly fuzz run -O <目標> <檔案>`；`WIME_FUZZ_TRACE=1` 會印出 `backend` 送的每個請求。
- 修好後把那個輸入放進 `fuzz/regressions/<目標>/`（取個說明問題的檔名），之後每次 CI 都會再檢查。
- `fuzz/corpus/`、`fuzz/artifacts/` 不進版本控制。

### 為什麼 panic 要特別處理

libfuzzer-sys 遇到 panic 會呼叫 `process::abort`，在 Windows 上是 `__fastfail`，行程直接結束，libFuzzer 來不及存下輸入。所以每個目標的 `init:` 呼叫 `init_libfuzzer()`，把 panic 改成 `raise(SIGABRT)` 交給 libFuzzer 處理。這個掛鉤在 unwind 之前就執行，所以程式自己接住的 panic（設定工具會回 500）也會被抓到。
