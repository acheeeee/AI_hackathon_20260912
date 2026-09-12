# 前處理工具現況

依據：[資料前處理與切分交接規格](../../docs/資料前處理與切分交接規格.md)。2026-09-12 依序產出 r2 與 r3。r3 以 `ext-2.0` 修正法規 PDF 的視覺閱讀順序，是目前可供證據層讀取的機械契約基線；仍未完成全量法律人工核對與評估 gold。詳見 [r3 稽核報告](../../sysdoc/verification/r3-audit.json)。

## 模組

`run.py` 清冊／流程／QA／評估分組 → `extract.py` 逐頁文字與座標 → `segment.py` 結構單元 → `chunk.py` 檢索段（offset 精確對應原行）→ `annotate.py` 欄位、案件類型／主文結果規則抽取、引用解析；`common.py` 管版本、ID、條號、案號與正規化。

## 已驗證的環境

- r1／r2／r3 抽取：現有 `.venv_pre/bin/python`，Python 3.9.6、PyMuPDF 1.26.5。依賴版本記於 [requirements.txt](requirements.txt)。
- 舊 API：`backend/.venv/bin/python`，Python 3.12.14、PyMuPDF 1.24.9。不能替代這個抽取環境；實測會改變產物。
- 本次沒有安裝／升級任何套件；乾淨環境安裝與其他 Python 版本未驗證。

## 執行

從 repo 根目錄，以 `.venv_pre` 環境執行：

```bash
.venv_pre/bin/python -m scripts.preprocess.run process  --input data --release <new-release-id>
.venv_pre/bin/python -m scripts.preprocess.run validate --release <new-release-id>
.venv_pre/bin/python -m scripts.preprocess.run splits   --release <new-release-id> --eval-version <new-eval-version>
```

`process` 會拒絕覆寫已存在的 release 目錄；不要對著 `r1`、`r2` 或 `r3` 重跑，實驗一律使用新 release ID。`--input` 預設是 `data`，會遞迴掃描整個 `data/`；只有 `annotate.CORPUS_CATEGORIES` 列出的四類（歷史訴願決定書／相關法規／行政函釋／司法院釋字及行政判解）算入 141 份基準語料，其餘（例如 12 份進件文件）明確排除並寫入 `excluded_non_corpus.jsonl`，不會混入。

## 只讀回歸檢查

```bash
.venv_pre/bin/python -m tests.preprocess.test_regression     # r2 歷史回歸
.venv_pre/bin/python -m tests.preprocess.test_statute_layout # r3 四法規版面回歸
.venv_pre/bin/python -m scripts.preprocess.run validate --release r3
```

`test_regression` 固定驗證 r2 的歷史行為；`test_statute_layout` 直接對四份本地法規 PDF 執行 bbox 視覺排序，驗證條號後緊接相應正文。r3 validator 另做 15 項發布契約檢查，包括 3,103 個 chunk 的全量 quote 重建、條號解析、外鍵與准入欄位。這些是工具／資料契約測試，不是法律標籤或全庫人工核對的替代品。

## r3 根因更正與已知殘留缺口

- **r2 的四法規判讀已更正**：原 PDF 可視讀到條號與正文，不需替換。問題是 PyMuPDF 的 block 原順序將左欄條號集中列在右欄正文之前；r3 對法規依 bbox 重建視覺順序，四法規版面回歸 4／4 PASS，2,214 個法條 section 的 `article_key` 解析失敗數為 0。
- **法規 metadata 部分留白**：`paragraph_path`（項／款／目層級切分）、`effective_from`／`effective_to`／`is_current` 均為 `null`——項款目切分本次未實作，生效狀態未經外部法規資料庫查證，誠實留白而非臆測。
- **101 件決定書的案件類型／主文結果**是規則式抽取（`review_status: unreviewed`），未逐案人工核對，不能作 gold 或硬過濾條件。
- **人工核對仍不足**：四份問題法規已各渲染第 1 頁做視覺版面 QA，但仍未完成規格 §8 的 20 份內容抽查、11 部法規逐條及 101 件決定書逐案覆核。
- **低文字頁仍待處理**：r3 review queue 剩 7 個低文字頁，機械准入與人工可引用性不能混為一談。
- **評估包不完整**：`data/evaluation/v1/splits.json` 只完成 dev／holdout 家族分組，未產生規格 §7.2 要求的合成輸入與 gold（`splits.json` 內以 `synthetic_inputs_status: not_generated` 明列）。

重現結果與失敗明細見 [驗證報告](../../sysdoc/驗證報告.md)（r1）、[r2 稽核報告](../../sysdoc/verification/r2-audit.json)（歷史中間產物）與 [r3 稽核報告](../../sysdoc/verification/r3-audit.json)（現行基線）。
