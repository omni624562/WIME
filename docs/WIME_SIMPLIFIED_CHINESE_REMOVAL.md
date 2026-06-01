# 移除簡體中文相關功能執行計劃

本文件整理 WIME 移除簡體中文相關功能的範圍、階段與驗收方式。目標是讓目前面向大易、新酷音、新酷倉的 WIME limited installer 成為繁體中文取向版本，同時保留必要相容性，避免舊設定或第三方資料造成升級風險。

目前結論：此計劃已完成 limited installer 與大易、新酷音、新酷倉相關的去簡體化範圍。full installer、Rime 與 source tree 內第三方 OpenCC/Rime 資料暫不列入本次完成範圍，僅保留為後續獨立決策。

## 移除範圍

移除或停用：

- 打繁出簡輸出轉換。
- `Ctrl+F12` 繁簡切換。
- 設定頁中的簡體輸出選項。
- 語言列/右鍵選單中的輸出簡體選項。
- ` 鍵功能選單中的輸出簡體選項。
- limited installer 中的 OpenCC 資料與簡體狀態 icon。
- limited installer 中的簡體安裝語系、Rime、拼音與速成。

不移除：

- 碼表或詞庫中可輸入「簡體字」等詞彙的資料。
- 「教育部國語辭典簡編本」這類繁體中文資源名稱。
- full installer 仍可能使用的第三方 Rime/OpenCC 資料，除非後續明確決定 full installer 也一起縮減。

## Phase 1：功能停用與入口移除

狀態：已執行。

- CIN 共用核心強制 `outputSimpChinese = false`。
- CIN 共用核心強制 `enableSwitchTCSC = false`。
- 新酷音強制 `outputSimpChinese = false`。
- 新酷音強制 `enableSwitchTCSC = false`。
- 移除 commit string 的 OpenCC 轉換流程。
- 移除設定頁與選單中的簡體輸出入口。
- 狀態 icon 永遠使用繁中 icon。

## Phase 2：設定相容性

狀態：已完成。

- 舊 config 載入後強制關閉簡體輸出與繁簡切換。
- 設定工具儲存時也寫回關閉狀態。
- 保留 `outputSimpChinese` 與 `enableSwitchTCSC` key 作為一版相容欄位，避免舊設定檔或舊工具讀取時發生例外。
- 保留相容欄位不代表功能仍存在；runtime、設定頁與 installer 都不再提供簡體輸出或繁簡切換。
- 若長期觀察無問題，後續可另開任務完全移除相容欄位。

## Phase 3：limited installer 清理

狀態：已執行。

- limited installer 僅包含大易、新酷音、新酷倉。
- 排除 `python/opencc`。
- 排除新酷音 `simC.ico`。
- 排除 CINBase `sim_*.ico`。
- limited installer 語言選單只保留繁體中文與英文。
- 確認封包內容不含 `opencc`、`simC`、`sim_`、`Rime`、`chepinyin`、`chesimplex`。

## Phase 4：full installer 決策

狀態：已決定採用選項 A。

選項 A：只讓 limited installer 去簡體化。

- 風險最低。
- 保留原 PIME full installer 的相容性。
- 適合目前大易、新酷音、新酷倉的發行節奏。

選項 B：full installer 也移除簡體分類。

- 需要調整 installer section group。
- 需決定 Rime、拼音、速成是否完全移除或只隱藏。
- 需要額外做完整安裝與解除安裝測試。

選項 C：source tree 也刪除 OpenCC/Rime 簡體資料。

- 風險最高。
- 可能影響 Rime menu conversion 或 full installer 使用者。
- 只有在確定 WIME 不再維護 full installer 相關簡體/拼音/Rime 功能時才建議執行。

目前本計劃停在 A，視為完成。B 與 C 不併入本次去簡體化完成範圍，若未來要處理 full installer 或 source tree 深層資料，應另開任務並重新評估 Rime/OpenCC 相依。

## 完成狀態

- limited installer 去簡體化：完成。
- 大易、新酷音、新酷倉使用者可見簡體輸出入口：移除完成。
- 舊設定強制關閉簡體輸出與繁簡切換：完成。
- full installer 深層去簡體化：本次不執行，保留相容性。
- source tree 刪除 OpenCC/Rime 第三方資料：本次不執行，保留相容性。

## 驗收清單

- 大易輸入、選字、候選窗 header/body 正常。
- 酷倉輸入、選字、候選窗 header/body 正常。
- 新酷音輸入、選字、候選窗與設定頁 tab 正常。
- 設定頁找不到簡體輸出與 `Ctrl+F12` 設定。
- 語言列/右鍵選單找不到「輸出簡體中文」。
- ` 鍵功能選單找不到「輸出簡體」。
- 舊 config 若曾開啟簡體輸出，升級後仍輸出繁體。
- limited installer 封包內容不含 OpenCC、簡體狀態 icon、Rime、拼音、速成。

## 固定驗證命令

```powershell
python -m py_compile python\cinbase\__init__.py python\cinbase\config.py python\cinbase\configtool.py python\input_methods\chewing\chewing_ime.py python\input_methods\chewing\chewing_config.py python\input_methods\chewing\config_tool.py
python -m unittest tests.test_backend_resilience
cargo test
pwsh -ExecutionPolicy Bypass -File .\build-test.ps1 -Platform Both
& 'C:\Program Files (x86)\NSIS\makensis.exe' /DONLY_DAYI_CHEWING_CHECJ installer\installer.nsi
```
