# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案性質

新北市政府 AI 黑客松參賽專案：**訴願案 AI 輔助處理系統**，協助訴願審議承辦人做法規推薦、時效提示、歷史相似案例比對、決定書草稿生成。系統**不做決定**，只產出有出處的草稿，決定權在承辦人與委員會。核心設計約束是「Zero Hallucination」——所有推薦的法條/函釋/判解必須來自知識庫檢索出的真實原文，抽不到就回傳 `null`，不允許 LLM 憑空編造。

實際程式碼都在 `app/` 目錄下；repo 根目錄的 `data/` 是官方提供的原始 PDF 語料（司法院釋字及行政判解、歷史訴願決定書、行政函釋、相關法規），`docs/` 是命題文件與開發策略文件。

## 常用指令

```bash
cd app
pip install -r requirements.txt

# 建立 app/.env，內容 GEMINI_API_KEY=你的key（https://aistudio.google.com/apikey）

# 建知識庫（PDF -> JSON，讀 repo 根目錄 data/，輸出到 app/data/kb/*.json）
python -m src.build_kb

# 建混合索引（BM25 + Gemini 向量，快取到 app/data/index/）
python -m src.build_index decisions refs   # 向量索引，耗 embedding 額度
python -m src.build_index statutes         # 法規只建 BM25，不耗額度

# 啟動（兩套並行入口，共用同一套 src/ pipeline）
streamlit run app.py                                  # Streamlit Demo UI
python3 -m uvicorn api:app --reload --port 8000        # FastAPI + 純 HTML/JS（app/web/）

# 不開 UI 的命令列檢索驗證
python -m src.demo_retrieval
```

目前**沒有自動化測試**（無 pytest 檔案）；開發文件 `docs/開發文件.md` §1.6 列出 10 件可作為期間計算模組測試集的官方案例，但尚未寫成測試程式。

## 架構

### 三套前端、一套 pipeline

- `app/app.py`（Streamlit Demo）
- `app/api.py`（FastAPI REST API）+ `app/web/`（舊的純手寫 HTML/JS/CSS 靜態頁，**已停止開發，保留但不再維護**）
- `app/api.py` + `frontend/`（**現役**：Vue 3 + TypeScript + Vite + Pinia + Vue Router + Element Plus，正在取代 `app/web`）

三者都呼叫同一套 `src/` pipeline，改 `src/` 會同時影響 Streamlit 與 FastAPI 兩條路徑。`frontend/` 開發時用 `npm run dev`（port 5173），`vite.config.ts` 設了 `/api` proxy 轉到 `localhost:8000`；`api.py` 也加了 `CORSMiddleware`（預設允許 `localhost:5173`，用 `CORS_ORIGINS` 環境變數覆寫），供前後端分開部署時使用。前端型別定義在 `frontend/src/types/appeal.ts`，對應 `src/models.py` 與 `api.py` 實際回傳的 JSON（注意 `draft.py` 的 `build_draft()` 回傳的是 `{fact, reason, main, mode}`，不是 `models.py` 裡定義但未被使用的 `DraftDecision`）。

**已知但刻意不修的缺陷**：`api.py` 用模組層級全域 `dict _last` 在 `/api/analyze` 與 `/api/draft` 之間傳狀態，多分頁／多 worker／多人同時使用會互相覆蓋（錄錯案）。目前決定先把前端接起來，這個 session-scoping 問題之後再處理。

**本機執行需求**：系統內建 Python 是 3.9（Xcode 帶的），裝不動 `numpy==1.26.4`／`pymupdf==1.24.9` 這組釘死版本在太新的 Python（試過 Homebrew 的 3.14，`pymupdf` 會從源碼編譯失敗）；改用 `brew install python@3.12` 建 venv（`app/.venv`，已 gitignore）才裝得起來。另外 `requirements.txt` 原本漏了 `fastapi`/`uvicorn`/`python-multipart`/`python-docx`（`api.py`／`docx_export.py` 實際會用到但沒寫進去），已補上。

### Pipeline 四階段

```
PDF/文字 ──intake──► IncomingAppeal ──recommend──► 法規/函釋/判解推薦 + 從新從輕時效提示
                                    └──similar───► 多維度相似歷史案例（前5）
                                                          │
                                                      draft 草稿（事實欄模板填空＋理由欄 LLM 三段論，法條 grounding）
```

- **`src/intake.py`**：`parse_incoming()` / `parse_incoming_pdf()`，把訴願書全文解析成 `IncomingAppeal`（規則優先 + 可選 LLM 補強）。
- **`src/recommend.py`**：`Stage2Recommender`，法規/函釋/判解的三路融合推薦＋時效提示（行政罰法 §5 從新從輕）。
- **`src/similar.py`**：`Stage3SimilarCases`，相似案例比對——**軸是 §77 款別／案件類型的結構化硬過濾，桶內才做語意排序**，不是單純向量相似度（`docs/開發文件.md` §4.2 有實驗數據說明為什麼純語意比對在這個領域會沿著錯誤的軸走）。
- **`src/draft.py`** + **`src/docx_export.py`**：組裝 `DraftDecision`（`origin` 欄位區分 template/filled/rule/LLM 四種來源）並匯出 Word。
- **`src/models.py`**：所有 Pydantic v2 資料模型（知識庫四類實體 `AppealDecision`/`StatuteArticle`/`Interpretation`/`CourtPrecedent`，以及 `IncomingAppeal`/`StatuteRecommendation`/`TimelinessAlert`/`SimilarCase` 等輸出結構）——要理解任何模組的輸入輸出，先看這裡。

### 檢索層：混合索引 + 自動降級

`src/retrieval.py` 的 `HybridIndex` = BM25（本地 jieba 斷詞，不耗額度）+ Gemini 向量 embedding（快取在 `app/data/index/*.pkl` + `*.npy`，由 `src/build_index.py` 一次性建立）。混合分數 = `alpha * 向量cos相似 + (1-alpha) * BM25正規化分數`。**沒有 API key 或額度耗盡時自動降級為純 BM25**，查詢路徑本身不中斷——改動檢索邏輯時要保留這個降級路徑。

### Provider 抽象層

`src/providers.py` 的 `get_provider()` 回傳單例 `GeminiProvider`，封裝 embedding（含 429 自動重試/節流）與生成。`.env` 由這裡手寫的極簡 parser 載入（非 python-dotenv，只會 `setdefault`，不覆蓋已存在的環境變數）。**換官方 API 時只需改這一個檔案**，其餘模組一律透過 `get_provider()` 呼叫，不要在別處直接 import Gemini SDK。

### 知識庫建置

`src/build_kb.py` 掃描 repo 根目錄 `data/`（由 `APPEALS_DATA_ROOT` 環境變數可覆寫）下的官方 PDF，用 `src/parsers.py` 抽取文字與欄位，輸出四份 JSON 到 `app/data/kb/`（decisions / statutes / interpretations / precedents）。這些 JSON 沒有被 `.gitignore`，會進版控；`app/data/index/` 的向量快取才是 gitignore 排除、可重建的。

## 領域邏輯的權威來源

`docs/開發文件.md` 是這個專案的領域知識權威文件（繁中，非常詳細），涵蓋：
- 訴願法 §77 八款「排除性確認」判準的法律邏輯與各款可驗證性（第 3、8 款是實質法律判斷，一律標 `NEEDS_HUMAN` 轉人工，不是偷懶是正確行為）。
- 期間計算規則（行政程序法 §48 IV/V 的雙重否定例外）。
- 行政罰法 §5 從新從輕的正確觸發條件（處分日前夕，不是決定日）。
- `CaseFacts`/`GateResult`/`DraftDecision` 的資料契約與稽核鏈設計。

修改 `recommend.py`／`similar.py`／`draft.py` 裡任何涉及法律判斷的邏輯前，先讀這份文件對應章節，裡面多處標註了「⚠ 未驗證假設」與「✓ 已實測」的區別，以及踩過的法律推理誤區（例如會議筆記原始設計中「上報機關錯誤」被誤當成不受理事由，實際上訴願法 §14 IV 規定這只影響提起日的認定）。

`app/README.md` 是使用者視角的快速上手文件（安裝、模型選擇、額度限制、誠實限制聲明）。
