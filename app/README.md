# 新北市訴願管理 AI 輔助系統

協助訴願承辦人「只需審核、無需從頭打字」的智慧工作流系統。聚焦**智能法規推薦（含時效提示）**與**歷史相似案例比對**兩大核心，並具備決定書草稿生成。

## 核心特色

- **Zero Hallucination（不胡說八道）**：所有推薦法規、函釋、草稿引用的法條，皆來自知識庫**檢索出的真實原文**，找不到原文的候選一律捨棄。LLM 只負責組織語言，不提供事實。
- **從新從輕時效提示**：自動比對行為時 / 處分時之間法規是否修正，觸發《行政罰法第 5 條》提示。
- **多維度可解釋相似度**：語意 + 案件類型 + 法條重疊三維度加權，附各維度分數與結果分佈統計。
- **混合檢索**：BM25（本地 jieba）+ 向量（Gemini embedding）。API 額度不足時自動降級純 BM25，系統照常運作。

## 系統架構

```
進件PDF ─► intake（分類+欄位擷取）─► IncomingAppeal
                                          │
              ┌───────────────────────────┼───────────────────────────┐
        階段二 recommend                階段三 similar             draft 草稿
     ├ 法規推薦(三路融合)            多維度相似案例(前5)         事實欄=模板填空
     ├ 函釋/判解檢索                 + 結果分佈統計             理由欄=LLM三段論
     └ 從新從輕時效提示                                         (法條grounding)
                                          │
                              retrieval（BM25+向量混合，快取）
                                          │
                       知識庫 data/kb/*.json（PDF解析而來）
```

## 資料規模（由官方 PDF 解析）

| 類別 | 筆數 | 索引 |
|------|------|------|
| 歷史訴願決定書 | 101 | BM25 + 向量 |
| 法規（逐條） | 1976 | BM25 |
| 行政函釋 | 10 | BM25 + 向量 |
| 司法院釋字及判解 | 19 | BM25 + 向量 |

> 法規採純 BM25：法條檢索靠精確關鍵字已足夠強，且可節省 embedding 每日額度。

## 快速開始

```bash
cd app
pip install -r requirements.txt

# 設定 API key（取得：https://aistudio.google.com/apikey）
# 在 app/ 下建立 .env，內容：GEMINI_API_KEY=你的key
# （未設定時自動降級為 BM25 檢索＋模板草稿，功能不中斷）

# 建立知識庫與索引（首次執行，會快取）
python -m src.build_kb        # PDF -> JSON
python -m src.build_index decisions refs           # 向量索引（耗額度）
python -m src.build_index statutes                 # 法規 BM25（不耗額度，use_vector 由腳本控制）

# 啟動 Demo
streamlit run app.py
```

命令列快速驗證（不需 UI）：
```bash
python -m src.demo_retrieval
```

## Vue 前端（取代 app/web 的新介面）

專案根目錄的 `frontend/` 是正在取代 `app/web`（純手寫 HTML/JS）的 Vue 3 + TypeScript + Element Plus 前端，透過 `api.py` 的 REST API 呼叫同一套 pipeline。`app/web` 暫時保留、未被移除。

```bash
# 後端（在 app/ 下執行，需先完成上面的 pip install -r requirements.txt）
python3 -m uvicorn api:app --reload --port 8000

# 前端（另一個終端機，frontend/ 在專案根目錄）
cd ../frontend
npm install
npm run dev          # http://localhost:5173，已設定 proxy 轉發 /api 到 :8000
```

開發時前端（Vite, port 5173）與後端（port 8000）是兩個不同 origin，`api.py` 已加上 CORS middleware 允許 `localhost:5173`；正式部署若前後端分開網域，記得用 `CORS_ORIGINS` 環境變數（逗號分隔）覆寫允許來源。

## 使用的模型（實測可用）

| 用途 | 模型 |
|------|------|
| LLM 生成 | `gemini-3.6-flash` |
| Embedding | `models/gemini-embedding-2`（3072 維） |

## 比賽當天換官方 API

只需修改 `src/providers.py` 的 `GeminiProvider`（或新增供應商類別），
其餘模組透過 `get_provider()` 介面呼叫，無需改動。

## 免費額度注意事項

Gemini 免費層 embedding 每日約 1000 次請求。建索引為一次性作業（之後讀快取）。
若當日額度耗盡，查詢會自動降級為 BM25，功能不中斷。

## 誠實限制說明

- 知識庫僅含**現行版本**法規，無歷史版本。從新從輕比對採「最新修正年度是否落在行為~處分區間」之**近似判斷**，非精確版本比對，UI 已提示承辦人確認。
- 草稿為 AI 輔助，須經承辦人審核定稿。
