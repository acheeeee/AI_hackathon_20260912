# 系統文件：訴願案 AI 輔助處理系統

盤點日期：2026-09-12｜範圍：目前 repo 的程式、資料、設計文件與本機流程｜狀態：整理完成，後續開發待使用者允許。

本文件描述**目前已存在且經查核的系統**。下一階段目標依 [協作設計](../docs/協作設計/README.md)；逐項測試證據見 [驗證報告](驗證報告.md)。

2026-09-12：舊後端目錄由 `app/` 更名為 `backend/`，內容未變；`verification/*.json` 保留更名前的路徑作為證據。

## 1. 判斷與工作邊界

目前有一套可執行的 Vue 前端與舊版 FastAPI／BM25／模板草稿流程，並有一套分離的前處理工具及 r1 產物。**兩條資料路徑尚未接起來，前端也尚未完成新協作設計。**

| 問題 | 盤點結論 |
|---|---|
| 前端能不能跑？ | 能。type check、build、lint 通過；瀏覽器走完示範解析→程序頁→依據頁→草稿→Word API。沒有前端單元測試，未驗證所有畫面／邊界情況。 |
| `backend/` 能刪嗎？ | 不能整包刪。它仍提供前端所需的分析、檢索、草稿及匯出 API。本次只刪除兩套已退役 demo UI。 |
| r1 是不是做完？ | 已產出，而且在原環境與原布局能逐檔重現；但未達交接規格。不能因 manifest 寫 `validated` 就直接全量索引。 |
| 下一步只有 RAG、LLM、API 嗎？ | 還包括資料契約修復、案件隔離、持久化、版本、人工操作與來源回查。新協作規格的能力大多尚未實作。 |
| 這輪是否繼續開發？ | 沒有。只做盤點、執行驗證、刪除舊介面／產物、修正文檔與必要入口。未新增 RAG／LLM／案件 API。 |

## 2. 目前程式架構

```mermaid
flowchart TD
  U[使用者：PDF 或示範文字] --> V[frontend：Vue 五步驟 wizard]
  V --> P[Vite 開發代理 /api]
  P --> API[backend/api.py：舊版 FastAPI]
  API --> I[intake / parsers：進件抽取]
  I --> R[recommend / similar]
  R --> IDX[backend/data/index：BM25 快取]
  KB[backend/data/kb：舊 JSON] -->|build_all| IDX
  API --> LAST[_last：程序全域狀態]
  LAST --> D[draft：模板或可選 LLM]
  D --> WORD[docx_export：Word]
  RAW[data/raw：原始 PDF] -. 現有布局不相容 .-> PRE[scripts/preprocess]
  PRE -. 舊布局可重現 .-> R1[data/processed/releases/r1]
  R1 -. 尚無讀取或索引串接 .-> FUTURE[新資料／RAG／協作 API：待開發]
```

### 2.1 現役前端

技術來源以 [package.json](../frontend/package.json)、[Vite 設定](../frontend/vite.config.ts) 為準。`router/index.ts` 只有 `/`，五步驟由 [case store](../frontend/src/stores/case.ts) 控制。

| 頁面 | 已存在的行為 | 實際限制 |
|---|---|---|
| Upload | 必要 PDF＋選填原處分 PDF；3 個文字示範；LLM 開關 | 其他附件只是展示說明。示範文本不是評估 gold。 |
| Extract | 顯示後端抽取欄位、摘要、推薦關鍵字 | 沒有欄位修正或逐頁／行 EvidenceRef；「AI 擷取」「有出處」是 UI 標籤，不能作為來源驗證。 |
| Gate | 八款人工點選狀態、舊時效提示 | 沒有 `gate.py`／完整期間引擎；狀態未送後端、未持久化。第 3／8 款固定待人工，第 5 款文案與可操作行為不一致。 |
| Select | 法條、函釋／判解、前例列表與勾選；原文連結 | 勾選只留前端。對「草稿只引用勾選內容」的承諾尚未實現。 |
| Draft | 模板／可選 LLM 草稿；三個文字區可改；Word 匯出 | 沒有版本、diff、採用、撤回、稽核；重新生成可重置人工內容。 |

前端對應 [design 稿件表](../docs/design/README.md)，但這不等於完成新 [協作設計](../docs/協作設計/README.md)。目前可見的日期、法律結論與提示仍需業務驗收，本次只判斷程式行為。

### 2.2 舊 API 與狀態

[client.ts](../frontend/src/api/client.ts) 呼叫 [api.py](../backend/api.py)：

| 端點 | 用途 | 本次狀態 |
|---|---|---|
| `GET /api/health` | SDK 可用旗標與存活回應 | PASS；不驗證索引完整性或模型可成功呼叫 |
| `POST /api/analyze` | multipart／form：`pdf`、`manual`、`text` | PASS；回傳欄位、6 法條、3 見解、5 前例等舊格式 |
| `POST /api/draft` | 以最近一次分析生成草稿 | PASS（模板）；request 沒有案件 ID 或勾選依據 |
| `POST /api/draft/docx` | 以 `main/fact/reason` 匯出 Word | PASS；已讀回 DOCX XML 核對三欄修改值 |
| `GET /api/decision/{doc_id}` | 舊 KB 決定書全文 HTML | PASS；不是原 PDF 或 r1 座標查詢 |
| `GET /api/reference/{doc_id}` | 舊 KB 函釋／判解全文 HTML | PASS；同上 |
| `GET /` | API 入口 | 清理後 307 導向 `/docs` |

`_last` 是 Python 程序全域 dict。分析、草稿、匯出共享最近一案；兩個使用者／分頁會互相覆蓋，多 worker 也不共享一致狀態。這是程式結構已確認的限制；本次沒有把它修成案件服務，也未執行負載／多人競爭測試。

目前沒有 SQLite、case revision、Proposal、EvidenceRef、SSE run events 或 `/api/v1`。API 的舊 `doc_id` 與 r1 的 `document_id/section_id/chunk_id` 不相容，未交付遷移映射。

### 2.3 檢索與模型

- [retrieval.py](../backend/src/retrieval.py) 讀取本地 pickle 中的 documents／texts，再建立 BM25。若存在 `.npy` 且 Provider 可用，才加入 query embedding。
- 本機索引是 `statutes.pkl`、`decisions.pkl`、`refs.pkl`，沒有向量檔。離線檢索與由舊 JSON 重建索引均實測通過。
- [recommend.py](../backend/src/recommend.py) 與 [similar.py](../backend/src/similar.py) 使用舊資料、條號與加權規則；不是新前處理 release 的檢索器。
- [providers.py](../backend/src/providers.py) 仍有舊 Gemini SDK／模型設定。**線上 LLM、embedding、額度與模型名稱可用性均 NOT RUN**；本次將兩個 API key 環境變數設空。
- 「本地原文被檢索出來」只證明來源存在，不能證明它支持本件法律結論；本次沒有評估檢索命中率或法律準確度。

## 3. 資料流程與 r1 判定

### 3.1 三種資料不要混用

| 層次 | 路徑 | 規模／用途 |
|---|---|---|
| 原件 | `data/raw/` | 153 PDF、755 頁：141 份語料（731 頁）＋12 份進件文件（24 頁） |
| 舊 runtime 語料 | `backend/data/kb/` | 法條 1,976、歷史案件 101、函釋 10、判解 19；現役 API 依賴它的索引 |
| 新前處理產物 | `data/processed/releases/r1/` | 141 documents、731 pages、2,623 sections、3,106 chunks、101 annotations、675 citations、7 review items |

153 個 Git 舊路徑的刪除與 `data/raw/` 新增，在本次開始前已存在。逐個對照 HEAD 原件，**153／153 的位元組完全一致**。本次沒有重做搬家、恢復舊路徑或提交這些變更。141 份 r1 來源都可用 SHA-256 找到搬家後原件，對照見 [source-relocation.json](verification/source-relocation.json)。

### 3.2 已驗證可保留的部分

- 所有 document／section／chunk 主鍵及既有結構檢查在原驗證器中通過。
- 本次另全查 2,623 個 section：span 範圍合法，quote 100% 可重建；非空白原文字元沒有未歸屬的遺失。
- 在暫存目錄重建原 `data/<分類>/` 布局，使用既有 **Python 3.9.6＋PyMuPDF 1.26.5**，完整跑兩次；8 個 JSONL 均與既有 r1 的 SHA-256 完全相同。
- 因此 r1 可以作為修復與再驗收的起點；不必因發現缺口就全部丟掉重做。

### 3.3 阻擋簽收的缺口

| 缺口 | 已確認的證據 | 對下一步的影響 |
|---|---|---|
| 原件路徑失效 | `documents.source_file` 141／141 指向搬家前路徑 | 原文查回 loader 會找不到檔；需新 release 或明確來源解析契約 |
| 現目錄無法重跑 | `--input data/raw` 讀到 153 PDF，分類全落未知，section／chunk 都為 0，exit 1 | 需修正分類／輸入基準；12 份進件不能無差別當語料 |
| chunk 引用不精確 | 623／3,106 個 quote 與其 spans 重建全文不同 | 不能把這些 spans 當精確引文定位；目前沿用整個 section 範圍 |
| 契約不完整 | 3,106 chunks 都缺 `chunking_version`；未交付完整 JSON Schema／Pydantic schema | loader 邊界與版本驗證尚未成立 |
| 法規 metadata 不完整 | 2,214 個法條 section 缺 `law_id`、`paragraph_path`、`source_version_id` 等多個規格欄位 | 2,214 是 parser 輸出數，並非人工認證的正確條文總數 |
| 發布清冊不足 | manifest 無設定／產物 hash 與完整成功／失敗／隔離帳 | 舊 `validated` 不足以證明可發布；本次旁錄 hash 不會補成原交付通過 |
| 關鍵標籤尚未完成 | 101 annotations 只抽案號、文號、日期、訴願人、機關；505 個欄位全 `unreviewed` | 未完成正文類型、結果、款別覆核，不能作 gold 或硬過濾 |
| 未決來源／人工覆核 | 675 引用全 `unresolved`、target 全空；7 低文字頁待處理，21 個 eligible chunks 觸及這些頁 | 未驗證不得冒充已 resolved／已覆核；需完成實際定位與准入判定 |
| 評估隔離缺失 | 101 決定書 `case_family_id` 全空；`data/evaluation/` 不存在 | 尚不能做符合規格的 dev／holdout 評估或防同案答案洩漏 |

本次詳細計數在 [r1-audit.json](verification/r1-audit.json)。這份報告是技術契約稽核，不是法律覆核收據。r1 內的 manifest／QA 保留原樣；使用時以本次「尚未簽收」判定補充舊標籤，避免改寫歷史證據。

### 3.4 重現性與環境差異

在 backend 的 Python 3.12.14＋PyMuPDF 1.24.9 環境，兩次重跑彼此相同，但得到 **3,108 chunks**；pages、sections、chunks、citations 的 hash 與 r1 不同。原前處理環境得到 3,106 chunks 且逐檔相符。

這是已驗證的**環境組合差異**；本次沒有單獨控制每一個變因，因此不將全部差異歸因於單一套件。應保留完整版本資訊；更新抽取器需新 extraction version、重建與重新驗收。

## 4. 執行與環境

### 4.1 本機已存在的環境

| 用途 | 路徑 | 本次版本 | 保存方式 |
|---|---|---|---|
| 前端 | `frontend/node_modules/` | Node 26.5.0、npm 11.17.0；Vue 等版本依 lock | 已由錯置的 `app/frontend/` 歸位；忽略版控 |
| 舊 API | `backend/.venv/` | Python 3.12.14、PyMuPDF 1.24.9 | 依 `backend/requirements.txt`；忽略版控 |
| r1 重現 | `.venv_pre/` | Python 3.9.6、PyMuPDF 1.26.5 | 本機保留，687 個環境檔移出 Git；版本記於獨立 requirements |

既有套件已足以完成本次驗證，沒有安裝、升級或啟用新服務。全新環境安裝與跨平台部署均未驗證。

### 4.2 啟動與檢查

從 repo 根目錄，兩個終端機分別執行：

```bash
cd backend
GEMINI_API_KEY='' GOOGLE_API_KEY='' .venv/bin/python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

開啟 `http://127.0.0.1:5173`。保持兩個 key 為空，才是這次已驗證的離線 BM25＋模板模式。API 根頁面現在導向 Swagger `/docs`。

本次 8000／5173 已有其他服務，因此另開 18000／15173，透過 Vite `createServer()` 僅在測試程序中覆寫 proxy 至 `127.0.0.1:18000`。沒有更改正式 Vite 設定，也沒有終止原有服務。

可重跑的現有檢查：

```bash
# repo 根目錄
backend/.venv/bin/python -m tests.preprocess.test_regression

# frontend/
npm run build
./node_modules/.bin/oxlint .
./node_modules/.bin/eslint .
npm run test:unit -- --run  # 沒有測試檔，預期 exit 1，不是 PASS

# backend/
GEMINI_API_KEY='' GOOGLE_API_KEY='' .venv/bin/python -m src.demo_retrieval
```

若缺舊索引，在 `backend/` 執行明確的離線函式入口：

```bash
GEMINI_API_KEY='' GOOGLE_API_KEY='' .venv/bin/python -c 'from src.build_index import build_all; build_all(use_vector=False)'
```

不要以 `python -m src.build_kb` 或 `python -m scripts.preprocess.run all` 當一般啟動指令。前者預設來源位置失效且可能覆寫空 KB；後者預設寫入 r1，當前布局也不相容。

### 4.3 乾淨環境與設定

未具備本機環境時，需另行準備 backend Python 3.12 venv 並依 `backend/requirements.txt` 安裝；frontend 依 `package-lock.json` 使用 `npm ci`，再離線重建舊索引。這是部署準備說明，**本次未執行乾淨安裝，也未保證過去舊套件在所有環境仍可安裝**。

前處理應使用獨立環境及 `scripts/preprocess/requirements.txt`，不能直接在 backend venv 升降 PyMuPDF。本次保留了能重現的原環境，新的 Python／平台組合仍需驗證。

機密只放程序環境或本機 env 檔，不寫入報告、不提交。正式站台的 `/api` 代理、使用者驗證、持久化、並行與備份都不在本次完成範圍。

## 5. 整理後的文件與刪除邊界

```text
README.md                     專案入口與最快啟動方式
AGENTS.md / CLAUDE.md          repo 工作規則；CLAUDE 指回共同規則
sysdoc/
  README.md                   本文件：實作現況與交接
  驗證報告.md                 本輪 PASS／FAIL／NOT RUN
  verification/               日誌、計數、hash、來源搬家對照、UI 讀回
docs/
  README.md                   文件用途與優先順序
  design/                     原始設計稿＋元件對照
  協作設計/                   下一階段五份設計與 README
  Reference/                  法律／資料背景、UI 討論、官方命題 PDF
  資料前處理與切分交接規格.md  資料交付契約
  北極星指南手冊.md           整體方向與需求背景
data/README.md                原件、release 與使用狀態
backend/README.md             舊版後端範圍與安全啟動
frontend/README.md            現役前端操作與限制
scripts/preprocess/README.md  前處理版本、重現限制與入口
```

本次刪除 `app/app.py`、`app/web/index.html`、`app/web/app.js`、`app/web/style.css`（當時目錄名為 `app/`）；同步移除 API 的舊靜態頁掛載並讓 `/` 導向 `/docs`。移除僅供退休 UI 或沒有程式引用的 `streamlit`／`scikit-learn` 直接依賴宣告，沒有卸載現有環境。

`app/frontend/` 原本沒有另一份前端程式，只有套件、lint cache、編輯器設定。套件與設定移到現役 `frontend/`，cache 刪除後移除空殼目錄。另刪 macOS `.DS_Store` 與部分 Python cache；`.venv_pre/` 只取消追蹤，實體保留。

既有設計、命題與法律來源仍有用途，全部保留；以索引與優先順序整理，不建立平行的第二套規格。原件、r1、舊 KB／有效索引也保留。詳細操作記於 [cleanup-actions.json](verification/cleanup-actions.json)。

未建立 commit、PR 或部署；`.venv_pre` 的 Git 索引移除是唯一預先 staged 的清理，其餘變更保留供 review。原先 153 個 PDF 搬家變動仍未替使用者提交。

## 6. 使用者允許後的交接順序

本節只描述既有設計要求的依賴關係，**不是開發授權或已完成清單**。

1. **先對齊資料與共同契約。** 修復 raw 分類／輸入基準、精確 chunk spans、版本與 schema、發布驗證；補人工覆核、案件家族、dev／holdout 隔離。保留 r1，交付新 release。
2. **建立最小案件狀態與 API。** 依協作設計階段 A 對齊 `case_id`、revision、EvidenceRef、TargetRef、Proposal；用 SQLite 與 fixtures 證明兩案不混、重整可恢復、未採用不改正文。沒有這層，直接串 LLM 會繼續依賴 `_last`。
3. **讓檢索先可驗證。** 用已驗收小批次建立來源 read／search／open 與 BM25 baseline；確定同案排除、引文定位與 dev 品質後再決定向量化。不能先把現有 3,106 chunks 無差別送去 embedding。
4. **接模型與協作。** 按階段 B–E 加查證解釋、局部修改、完整候選、diff／採用、取消／重啟與整合驗收；LLM Provider 選型與額度另查。

每階段完成狀態應回寫 [協作設計的驗收表](../docs/協作設計/05-實作順序與驗收.md)，並以真實執行結果更新 sysdoc。現有表格仍為 NOT RUN，這次沒有冒充新功能通過。
