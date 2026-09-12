# 舊版相容後端

**仍被根目錄 `frontend/` 使用，因此保留。** 本目錄不是新版協作架構，也沒有讀取 `data/processed/releases/r1`。

本目錄 2026-09-12 由 `app/` 更名為 `backend/`；`sysdoc/verification/*.json` 等歷史紀錄仍使用更名前的 `app/` 路徑。

- `api.py`：現有 `/api/*`，`/` 導向 `/docs`。
- `src/`：進件抽取、BM25／可選向量檢索、法規推薦、相似案例、模板／可選 LLM 草稿、Word 匯出。
- `data/kb/`：4 個舊 JSON 語料檔，合計 2,106 筆；不能與 r1 的 document／chunk ID 混用。
- `data/index/`：由舊 JSON 重建的本機快取，未納版控。現有快取只有 BM25，沒有 `.npy` 向量。
- `.venv/`：本機 Python 3.12 環境，未納版控。

## 執行

```bash
GEMINI_API_KEY='' GOOGLE_API_KEY='' .venv/bin/python -m uvicorn api:app --host 127.0.0.1 --port 8000
GEMINI_API_KEY='' GOOGLE_API_KEY='' .venv/bin/python -m src.demo_retrieval
```

若索引不存在，可由既有 JSON 重建純 BM25（在 `backend/` 下）：

```bash
GEMINI_API_KEY='' GOOGLE_API_KEY='' .venv/bin/python -c 'from src.build_index import build_all; build_all(use_vector=False)'
```

這會寫入 `backend/data/index/`，不會重建／覆寫 `backend/data/kb/`，也不會讀取 r1。本次已在暫存索引目錄驗證此函式的重建與檢索。

## 不適合作為新開發起點的部分

- `_last` 是程序全域狀態，沒有案件隔離、SQLite 或版本；只適用單一使用者示範。
- `build_kb.py` 的預設原件位置已失效，掃不到檔仍可能覆寫空 JSON；不要直接執行。
- `build_index.py` 有重複的 `__main__`，CLI 可能重建兩次；重建離線索引使用上面明確的函式入口。
- Provider 的模型名稱只是舊程式預設，本次沒有查證／執行線上 LLM 或 embedding。
- 舊 UI `app.py`（Streamlit）與 `web/`（手寫 HTML）已刪除；使用根目錄 `frontend/`。

完整現況、驗證結果與下一階段依據見 [sysdoc](../sysdoc/README.md)。
