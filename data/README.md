# 資料目錄與使用限制

2026-09-12 已按 SHA-256 核對：原先 Git 路徑下刪除的 153 個 PDF，都能在 `raw/` 找到相同位元組。搬家是本次工作開始前既有變更；本次沒有改寫或重命名原件。同日依序產出 r2 與 r3；兩者都使用同一批原件位元組。

| 位置 | 內容 | 使用狀態 |
|---|---|---|
| `raw/司法院釋字及行政判解/` | 19 份判解／釋字 | r1／r2／r3 共同來源 |
| `raw/歷史訴願決定書/` | 101 份歷史決定書 | r1／r2／r3 共同來源 |
| `raw/行政函釋/` | 10 份函釋 | r1／r2／r3 共同來源 |
| `raw/相關法規/` | 11 份法規 | r1／r2／r3 共同來源 |
| 上述四類合計 | 141 份、731 頁 | 三個 release 的來源語料（基準批次） |
| `raw/訴願書予行政處分函-1/` | 12 份、24 頁進件文件 | 不在 141 份基準批次；r2/r3 工具會掃到但明確排除，記錄於各 release 的 `excluded_non_corpus.jsonl` |
| `processed/releases/r1/` | documents／pages／sections／chunks 等 8 個 JSONL＋manifest／QA | **保留原樣**，供對照與重現；未達完整驗收，不可簽收為 RAG 輸入 |
| `processed/releases/r2/` | 同上 8 個 JSONL＋`excluded_non_corpus.jsonl`＋manifest／QA | 2026-09-12 新產出，修復 r1 的多項技術契約缺口；仍有已知殘留缺口，見下方 |
| `processed/releases/r3/` | 同 r2 的發布檔案 | 現行機械契約基線；修正法規 PDF 閱讀順序，可供新版 `EvidenceRepository` 離線讀取 |
| `evaluation/v1/` | `splits.json`（dev／holdout 家族分組） | 2026-09-12 新產出；只有分組，未產生合成輸入／gold |

## r1：保留但不可直接簽收為 RAG 輸入

原 manifest 的 `validated` 只代表舊驗證器的 13 項檢查通過。現查發現 141 個原件路徑失效、623 個 chunk 的 quote 無法由自己的 spans 重建、版本／schema／關鍵標註與評估交付不完整。詳見 [sysdoc 資料現況](../sysdoc/README.md#3-資料流程與-r1-判定) 與 [驗證報告](../sysdoc/驗證報告.md)。

未修改 r1 的 manifest 或內容，以保留既有交付的證據。來源搬家對照在 [source-relocation.json](../sysdoc/verification/source-relocation.json)，它是本次盤點證據，不是已接進 runtime 的 loader。

## r2：修復多項缺口的歷史中間產物

依使用者要求於 r1 之後另行產出，**沒有覆寫或修改 r1**。修復內容：來源路徑可解析（改用 `data/raw/<分類>/` 布局判別）、全部 2,834 個 chunk 的 quote 可由自己的 source_spans 100% 重建（非抽查）、`chunking_version` 齊全、manifest 含 config／每個檔案的 sha256、101 件決定書皆有 `case_family_id`、675 個引用中 227 個已對照本 release 內的法規條文解析出 `target_id`、兩次重跑產出的檔案 hash 完全相同（可重現）。

當時把 4 部法規判成「PDF 只有跳頁小工具、缺少可信條文標題」。這是 r2 的歷史判讀，後來以版面座標與頁面渲染確認為錯：PDF 本身是可讀的「所有條文」版面，只是 PyMuPDF block 原順序先列左欄條號、再列右欄正文。r2 保留作中間產物，根因更正與修復見下一節。

**仍未完成，不能視為已驗收**：101 件決定書的案件類型／主文結果是規則式抽取（`review_status: unreviewed`），未逐案人工核對；11 部法規條號未逐一人工核對 PDF（本次僅 6 份文件定向抽查，遠低於規格要求的 20 份）；`data/evaluation/v1/splits.json` 只完成 dev／holdout 家族分組，未產生規格 §7.2 要求的合成輸入與 gold；未接入向量化或線上 LLM／embedding。

`scripts/preprocess/run.py` 現在依 `data/raw/<分類>/` 判別類型，且會明確排除 `訴願書予行政處分函-1`（12 份進件文件），不會再把 153 份全標成未知類型。重跑指令與各步驟見 [scripts/preprocess/README.md](../scripts/preprocess/README.md)。

## r3：修正法規閱讀順序，可作機械證據層基線

r3 沒有下載、替換或修改任何原 PDF。`ext-2.0` 對法規頁面依文字 bbox 的視覺位置排序，再沿用 r2 的切分、精確 spans、案件家族與准入規則。結果：141 documents、731 pages、2,627 sections、3,103 chunks，其中 3,002 個 `index_eligible=true`，101 個歷史主文 chunk 依既定規則排除；2,214 個 `statute_article` 全部有可解析 `article_key`，章節退場項為 0；675 個引用中 588 個能解析到本 release 的法規條文。

release validator 為 15／15 PASS，3,103 個 chunk 都能從自己的 spans 逐字重建；最終 r3 與兩次獨立暫存重跑的 9 個 JSONL hash 全部一致。新版 `backend/caseapi/evidence/` 會先核對 manifest 與必要 artifact hash，再只對准入 chunk 建 BM25，並把來源回查標為 `snapshot_only`。完整證據見 [r3 稽核報告](../sysdoc/verification/r3-audit.json)。

**仍未完成，不能視為法律覆核或評估簽收**：11 部法規未逐條人工核對；101 件決定書的案件類型／主文結果仍是 `unreviewed`；7 個低文字頁仍待人工判定；評估包仍只有家族 split，沒有合成 inputs／gold；法規生效期間欄位仍為 null；未接線上 LLM／embedding。

舊後端仍用 `backend/data/kb/` 與 `backend/data/index/`；新版 `EvidenceRepository` 已直接讀 r3，但尚未接入 `/api/v1` run、`evidence_records` 或現有前端。
