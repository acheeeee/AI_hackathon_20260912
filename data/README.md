# 資料目錄與使用限制

2026-09-12 已按 SHA-256 核對：原先 Git 路徑下刪除的 153 個 PDF，都能在 `raw/` 找到相同位元組。搬家是本次工作開始前既有變更；本次沒有改寫或重命名原件。

| 位置 | 內容 | 使用狀態 |
|---|---|---|
| `raw/司法院釋字及行政判解/` | 19 份判解／釋字 | r1 來源 |
| `raw/歷史訴願決定書/` | 101 份歷史決定書 | r1 來源 |
| `raw/行政函釋/` | 10 份函釋 | r1 來源 |
| `raw/相關法規/` | 11 份法規 | r1 來源 |
| 上述四類合計 | 141 份、731 頁 | r1 的來源語料 |
| `raw/訴願書予行政處分函-1/` | 12 份、24 頁進件文件 | 不在 r1；不要混入 141 份基準批次 |
| `processed/releases/r1/` | documents／pages／sections／chunks 等 8 個 JSONL＋manifest／QA | 保留原樣供修復與重現，尚未完整驗收 |

## r1 不可直接簽收為 RAG 輸入

原 manifest 的 `validated` 只代表舊驗證器的 13 項檢查通過。現查發現 141 個原件路徑失效、623 個 chunk 的 quote 無法由自己的 spans 重建、版本／schema／關鍵標註與評估交付不完整。詳見 [sysdoc 資料現況](../sysdoc/README.md#3-資料流程與-r1-判定) 與 [驗證報告](../sysdoc/驗證報告.md)。

未修改 r1 的 manifest 或內容，以保留既有交付的證據。新 release 應在使用者允許開發後另行修正、驗證，不要覆寫 r1。來源搬家對照在 [source-relocation.json](../sysdoc/verification/source-relocation.json)，它是本次盤點證據，不是已接進 runtime 的 loader。

`scripts/preprocess/run.py` 仍依舊 `data/<分類>` 判別類型。直接改傳 `--input data/raw` 不會解決問題，反而會把 153 份全標成未知類型，實測產生 0 個 section／chunk。不要直接重跑正式 release。

舊後端仍用 `backend/data/kb/` 與 `backend/data/index/`；它們與 r1 是兩條分離的資料路徑。`data/evaluation/` 目前不存在。
