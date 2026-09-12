# 訴願案 AI 輔助處理系統

協助承辦人整理案件、檢索法規與歷史前例、編修決定書草稿。決定與法律覆核由人負責。

**2026-09-13 現況：新前端首頁（案件列表＋上傳＋原檔展開＋AI 側邊欄＋程序審查＋選法規）已接上新版案件 API；新版案件 API、r3/BM25 證據層、run／事件、Evidence 工具、固定假模型端到端流程、線上 AWS Bedrock AgentCore provider、上傳建案（訴願書規則式抽欄位＋案件列表狀態）、AI 對話側邊欄、訴願法第14條期間試算與選法規（真 BM25 搜尋＋人工挑選）都已完成並用真實請求、真實樣本或真人瀏覽器操作驗證過。舊的五步驟精靈搬到 `/legacy-demo`，仍走舊後端 `/api/*`，兩邊不共用狀態。**

- [系統文件 sysdoc](sysdoc/README.md)：目前架構、功能邊界、資料缺口、啟動方法及後續交接。
- [本次驗證報告](sysdoc/驗證報告.md)：PASS／FAIL／NOT RUN 與實測證據。
- [文件閱讀入口](docs/README.md)：設計稿、資料規格、協作設計的關係與優先順序。
- [資料目錄說明](data/README.md)：153 份原件、141 份語料、r1／r2／r3 三個 release 及發布限制。

## 目錄

```text
frontend/           現役 Vue 3 / TypeScript 介面
backend/            仍供 frontend 使用的舊版 FastAPI 與檢索程式
data/raw/           原始 PDF（141 份語料＋12 份進件文件）
data/processed/     前處理 release；r1/r2 保留歷史，r3 修正法規閱讀順序
scripts/preprocess/ 前處理程式與獨立依賴版本
tests/preprocess/   既有前處理回歸檢查
docs/               需求、設計與法律來源文件
sysdoc/             現況架構與驗證交接文件
```

`backend/`（原 `app/`，2026-09-12 更名）**不能整包刪除**：現役前端依賴它的 `/api/analyze`、`/api/draft`、Word 匯出及原文查詢。已刪除舊 Streamlit 與手寫 HTML demo；唯一操作介面是 `frontend/`。

## 啟動既有離線示範

以下使用本機已存在的環境與索引；不需要雲端模型。從 repo 根目錄開兩個終端機：

```bash
cd backend
GEMINI_API_KEY='' GOOGLE_API_KEY='' .venv/bin/python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

操作頁：<http://127.0.0.1:5173>；API 文件：<http://127.0.0.1:8000/docs>。若埠已占用，先辨識既有服務；不要直接終止別人的程序。本次驗證使用獨立的 15173／18000，完成後關閉。

乾淨 checkout 缺少環境／索引時，依 [sysdoc 執行說明](sysdoc/README.md#4-執行與環境) 準備；不要直接執行舊 `build_kb` 覆寫資料。

## 前處理 release 環境

`.venv_pre/` 是 r1／r2／r3 前處理 release 的**本機重現環境**，目前驗證的組合為 Python 3.9.6 與 PyMuPDF 1.26.5。要檢查既有 release、重建新的 release，或調整前處理程式時應保留它；它不參與一般前端／舊 API 的啟動。

不要以 `backend/.venv/` 取代它：該環境使用 Python 3.12 與 PyMuPDF 1.24.9，已實測會產生不同的前處理結果。`.venv_pre/` 已由 Git 忽略，不能提交；依賴版本定義在 [scripts/preprocess/requirements.txt](scripts/preprocess/requirements.txt)。若不再需要重現或驗證 release 才可刪除，之後必須依該 requirements 重建並重新驗證，且只能輸出新的 release ID，不能覆寫 `r1`、`r2` 或 `r3`。

從 repo 根目錄可用它執行既有驗證：

```bash
.venv_pre/bin/python -m tests.preprocess.test_regression
.venv_pre/bin/python -m tests.preprocess.test_statute_layout
.venv_pre/bin/python -m scripts.preprocess.run validate --release r3
```

## 目前能信任到哪裡

- 前端 build、type check、lint 通過；沒有前端單元測試檔。
- 舊 API 的表單、文字、雙 PDF 分析、模板草稿與 Word 內容匯出通過；不代表法律判斷正確。
- r1 可在原抽取器版本與原目錄布局重現，但來源路徑失效、623 個 chunk 引用座標不精確，尚不能直接簽收為 RAG 輸入。
- r2 修復來源路徑、chunk 座標、版本、案件家族與部分引用解析；其「4 部法規只能章節切分」結論後來確認是抽取閱讀順序誤判，不是原 PDF 缺資料。
- r3 使用同一批、位元組未改的原 PDF，依 bbox 還原法規視覺閱讀順序：15／15 資料檢查通過，2,214 個法條 section 均有可解析條號，3,103 個 chunk 的 quote 全量可重建；仍未完成法律人工覆核與評估 gold。詳見 [r3 稽核報告](sysdoc/verification/r3-audit.json)。
- 新 `/api/v1` 的案件隔離、SQLite、版本、提案／diff／採用已完成階段 A；B0／B1／B2 已完成 r3 BM25、run 與工具。B3 已加入案件內對話、固定 provider、背景 runner、assistant message、evidence GET 與 Last-Event-ID SSE replay；實測可經真實 r3 完成 search→open→answer。線上 provider（AWS Bedrock AgentCore Runtime）已部署並用真實請求跑通同一條鏈路，見 [07](docs/協作設計/07-AgentCore部署與線上模型.md)。長連線 SSE worker 與前端串接仍未完成。
