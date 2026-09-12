# 舊版相容後端

**仍被根目錄 `frontend/` 使用，因此保留。** 舊 `api.py` 不讀新 release；同目錄下的新版 `caseapi/` 已有獨立案件 API 與 r3 證據讀取層，但兩者尚未接到現有 Vue 流程。

本目錄 2026-09-12 由 `app/` 更名為 `backend/`；`sysdoc/verification/*.json` 等歷史紀錄仍使用更名前的 `app/` 路徑。

- `api.py`：現有 `/api/*`，`/` 導向 `/docs`。
- `src/`：進件抽取、BM25／可選向量檢索、法規推薦、相似案例、模板／可選 LLM 草稿、Word 匯出。
- `data/kb/`：4 個舊 JSON 語料檔，合計 2,106 筆；不能與 r1 的 document／chunk ID 混用。
- `data/index/`：由舊 JSON 重建的本機快取，未納版控。現有快取只有 BM25，沒有 `.npy` 向量。
- `.venv/`：本機 Python 3.12 環境，未納版控。

## 新版案件 API（`caseapi/`）

依 [協作設計](../docs/協作設計/README.md) 實作的新後端，與本目錄的舊 `api.py` 並存，不共用狀態。舊 `/api/*` 未改動；新契約掛在 `/api/v1`。

- `caseapi/db/`：SQLite 連線、短交易與 migration。
- `caseapi/evidence/`：讀取不可變 r3 release，先驗 manifest／artifact hash，再對 `index_eligible=true` 的 chunk 建離線 BM25；可排除同案件家族、開啟精確來源並核對 quote。
- `caseapi/tools/evidence_tools.py`：四個案件受限工具。每次呼叫由伺服器追加 activity；search 不落 evidence，`open_source` 在同一交易寫 program-verified evidence 與 `source.opened`。
- `caseapi/services/run_service.py`：凍結 run context、queued job、狀態轉移與每個 run 單調遞增的 append-only 事件。
- `caseapi/api/routes_runs.py`：讀 run、以 `after_sequence` 分頁 replay JSON 事件、冪等取消未完成 run；SSE 尚未實作。
- `caseapi/schemas/`：請求與回應的 Pydantic 模型，含 TargetRef。
- `caseapi/services/`：案件、資源版本、事實、草稿、註記、提案、三方合併與採用。寫入函式假設呼叫端已開交易。
- `caseapi/api/`：端點與共用的冪等流程。

```bash
.venv/bin/python -m pytest
.venv/bin/python -m uvicorn caseapi.main:app --host 127.0.0.1 --port 8001
```

目前測試結果為 83 passed，`caseapi` 總覆蓋率 94%，其中 `EvidenceToolAdapter` 93%、`EvidenceRepository` 87%。資料庫預設寫入 `data/caseapi.db`，未納版控；用 `CASEAPI_DB_PATH` 可改位置。測試依賴在 `requirements-dev.txt`。

證據層的最小用法（從 `backend/` 執行）：

```python
from pathlib import Path

from caseapi.evidence import EvidenceRepository

repo = EvidenceRepository(
    Path('../data/processed/releases/r3'),
    expected_release_id='r3',
)
hits = repo.search('訴願應自行政處分達到次日起三十日內提起')
source = repo.open_source(hits[0].chunk_id)
```

EvidenceRepository 已由 `EvidenceToolAdapter` 包裝；它還沒有聊天入口、SSE、模型協調器或前端來源卡。目前只有 adapter 的 `open_source` 可寫程式驗證的 `evidence_records`；階段 A fixture 提案傳入的 evidence 仍為 `unverified`。實作進度與已知缺口見 [協作設計 05 §6](../docs/協作設計/05-實作順序與驗收.md)；接手實作先讀 [協作設計 06 交接](../docs/協作設計/06-交接與下一步.md)。

## 舊版執行

```bash
GEMINI_API_KEY='' GOOGLE_API_KEY='' .venv/bin/python -m uvicorn api:app --host 127.0.0.1 --port 8000
GEMINI_API_KEY='' GOOGLE_API_KEY='' .venv/bin/python -m src.demo_retrieval
```

若索引不存在，可由既有 JSON 重建純 BM25（在 `backend/` 下）：

```bash
GEMINI_API_KEY='' GOOGLE_API_KEY='' .venv/bin/python -c 'from src.build_index import build_all; build_all(use_vector=False)'
```

這會寫入 `backend/data/index/`，不會重建／覆寫 `backend/data/kb/`，也不會讀取 r1/r2/r3。本次已在暫存索引目錄驗證此函式的重建與檢索。

## 不適合作為新開發起點的部分

- `_last` 是程序全域狀態，沒有案件隔離、SQLite 或版本；只適用單一使用者示範。
- `build_kb.py` 的預設原件位置已失效，掃不到檔仍可能覆寫空 JSON；不要直接執行。
- `build_index.py` 有重複的 `__main__`，CLI 可能重建兩次；重建離線索引使用上面明確的函式入口。
- Provider 的模型名稱只是舊程式預設，本次沒有查證／執行線上 LLM 或 embedding。
- 舊 UI `app.py`（Streamlit）與 `web/`（手寫 HTML）已刪除；使用根目錄 `frontend/`。

完整現況、驗證結果與下一階段依據見 [sysdoc](../sysdoc/README.md)。
