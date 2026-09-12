"""
FastAPI 後端 — 包裝訴願 AI 系統的四大功能為 REST API。
啟動：
    cd app
    python3 -m uvicorn api:app --reload --port 8000
    瀏覽器開 http://localhost:8000

端點：
    GET  /                      單頁介面
    POST /api/analyze           進件分析（PDF 或表單）→ 分類/法規/時效/相似案例
    POST /api/draft             生成決定書草稿
    POST /api/draft/docx        下載 Word 草稿
    GET  /api/decision/{doc_id} 相似案例完整決定書原文（新視窗）
    GET  /api/health            健康檢查
"""
from __future__ import annotations
import os
import sys
import tempfile
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
import io

from src.intake import parse_incoming
from src.parsers import extract_text
from src.recommend import Stage2Recommender
from src.similar import Stage3SimilarCases
from src.draft import build_draft
from src.docx_export import build_docx
from src.providers import get_provider
from src.models import IncomingAppeal

app = FastAPI(title="新北市訴願管理 AI 輔助系統")

# 前端（Vue, app/frontend）開發時跑在獨立 port（Vite 預設 5173），屬跨來源請求。
# 正式環境若前後端分開部署，改用 CORS_ORIGINS 環境變數覆寫（逗號分隔）。
_default_origins = "http://localhost:5173,http://127.0.0.1:5173"
_cors_origins = os.environ.get("CORS_ORIGINS", _default_origins).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")

# 引擎單例（載入索引一次）
_r2: Optional[Stage2Recommender] = None
_r3: Optional[Stage3SimilarCases] = None


def engines():
    global _r2, _r3
    if _r2 is None:
        _r2 = Stage2Recommender()
    if _r3 is None:
        _r3 = Stage3SimilarCases()
    return _r2, _r3


# 簡易快取，供 draft / docx 取用最近一次分析結果
_last: dict = {}


@app.get("/", response_class=HTMLResponse)
def index():
    path = os.path.join(WEB_DIR, "index.html")
    with open(path, encoding="utf-8") as f:
        return f.read()


@app.get("/api/health")
def health():
    prov = get_provider()
    return {"status": "ok", "gemini": prov.available}


def _build_appeal(text: str, manual: Optional[dict], use_llm: bool) -> IncomingAppeal:
    if manual:
        return IncomingAppeal(
            case_type=manual.get("case_type") or None,
            appellant=manual.get("appellant") or None,
            original_authority=manual.get("original_authority") or None,
            disposition_no=manual.get("disposition_no") or None,
            facts=manual.get("facts") or None,
            claims=manual.get("claims") or None,
            behavior_date_roc=_to_int(manual.get("behavior_date_roc")),
            disposition_date_roc=_to_int(manual.get("disposition_date_roc")),
            full_text=text or " ".join(filter(None, [
                manual.get("case_type"), manual.get("facts"), manual.get("claims")])),
        )
    return parse_incoming(text, use_llm=use_llm)


def _to_int(v):
    try:
        return int(v) if v not in (None, "", "0") else None
    except (ValueError, TypeError):
        return None


@app.post("/api/analyze")
async def analyze(
    mode: str = Form("pdf"),                 # 'pdf' | 'manual' | 'text'
    use_llm: bool = Form(False),
    pdf: Optional[UploadFile] = File(None),   # 訴願書
    pdf2: Optional[UploadFile] = File(None),  # 原處分書（選填，會併入分析文本）
    text: str = Form(""),
    # 手動輸入欄位
    case_type: str = Form(""),
    appellant: str = Form(""),
    original_authority: str = Form(""),
    disposition_no: str = Form(""),
    facts: str = Form(""),
    claims: str = Form(""),
    behavior_date_roc: str = Form(""),
    disposition_date_roc: str = Form(""),
):
    # 取得文字
    full_text = text or ""
    if mode == "pdf":
        if pdf is None:
            raise HTTPException(400, "未上傳 PDF")
        # 訴願書為必要，原處分書（pdf2）為選填；兩份都抽取後併入同一分析文本，
        # 以標題分隔，讓 intake 能同時看到兩份文件的內容。
        parts: list[str] = []
        for label, upload in (("訴願書", pdf), ("原處分書", pdf2)):
            if upload is None:
                continue
            data = await upload.read()
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            try:
                doc_text, _ = extract_text(tmp_path)
            finally:
                os.unlink(tmp_path)
            if doc_text and doc_text.strip():
                parts.append(f"【{label}】\n{doc_text.strip()}")
        full_text = "\n\n".join(parts)

    manual = None
    if mode == "manual":
        manual = dict(
            case_type=case_type, appellant=appellant, original_authority=original_authority,
            disposition_no=disposition_no, facts=facts, claims=claims,
            behavior_date_roc=behavior_date_roc, disposition_date_roc=disposition_date_roc,
        )

    appeal = _build_appeal(full_text, manual, use_llm)
    r2, r3 = engines()

    recs = r2.recommend_statutes(appeal, top_k=6)
    refs = r2.recommend_refs(appeal, top_k=3)
    alert = r2.timeliness_alert(appeal, recs)
    sims = r3.find_similar(appeal, top_k=5, recommended_statutes=recs)
    dist = r3.result_distribution(sims)

    # 快取供草稿使用
    _last["appeal"] = appeal
    _last["recs"] = recs
    _last["sims"] = sims
    _last["alert"] = alert
    _last["dist"] = dist
    _last["use_llm"] = use_llm

    return JSONResponse({
        "appeal": {
            "case_type": appeal.case_type,
            "appellant": appeal.appellant,
            "original_authority": appeal.original_authority,
            "disposition_no": appeal.disposition_no,
            "behavior_date_roc": appeal.behavior_date_roc,
            "disposition_date_roc": appeal.disposition_date_roc,
            "facts": appeal.facts,
            "claims": appeal.claims,
        },
        "statutes": [r.model_dump() for r in recs],
        "refs": [r.model_dump() for r in refs],
        "timeliness": alert.model_dump(),
        "similar": [s.model_dump() for s in sims],
        "distribution": dist,
        "gemini": get_provider().available,
    })


@app.post("/api/draft")
def draft():
    if "appeal" not in _last:
        raise HTTPException(400, "請先執行分析")
    d = build_draft(_last["appeal"], _last["recs"], _last["sims"],
                    _last.get("alert"), _last.get("dist"),
                    use_llm=_last.get("use_llm", False))
    _last["draft"] = d
    return JSONResponse(d)


@app.post("/api/draft/docx")
def draft_docx(edited: Optional[dict] = Body(default=None)):
    """匯出 Word。若帶入 edited（承辦人於前端修改後的 main/fact/reason），
    則以修改後版本匯出，否則使用最近一次生成的草稿。"""
    if "draft" not in _last and not edited:
        # 若尚未生成則即時生成
        draft()
    appeal = _last.get("appeal")
    meta = {
        "case_type": getattr(appeal, "case_type", None),
        "appellant": getattr(appeal, "appellant", None),
        "original_authority": getattr(appeal, "original_authority", None),
        "disposition_no": getattr(appeal, "disposition_no", None),
    }
    base = dict(_last.get("draft") or {})
    if edited:
        for key in ("main", "fact", "reason"):
            if isinstance(edited.get(key), str):
                base[key] = edited[key]
    content = build_docx(base, meta)
    headers = {"Content-Disposition": 'attachment; filename="appeal_draft.docx"'}
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )


@app.get("/api/decision/{doc_id}", response_class=HTMLResponse)
def decision_full(doc_id: str):
    """相似案例的完整決定書原文（新視窗開啟，簡易排版）。"""
    r2, r3 = engines()
    for d in r3.decisions.docs:
        if str(d.get("doc_id")) == doc_id:
            title = f"{d.get('year')}年 {d.get('case_type')} — {d.get('result')}"
            body = (d.get("full_text") or "").replace("&", "&amp;").replace("<", "&lt;")
            html = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>{title}</title><style>
body{{font-family:'Noto Serif TC',serif;max-width:820px;margin:40px auto;padding:0 24px;
line-height:1.9;color:#1a2b4a;}}
h1{{font-size:18px;border-bottom:3px solid #0b3d91;padding-bottom:10px;color:#0b3d91;}}
pre{{white-space:pre-wrap;font-family:inherit;font-size:15px;}}
.meta{{background:#f4f7fc;padding:12px 16px;border-radius:8px;margin:16px 0;font-size:14px;}}
</style></head><body>
<h1>{title}</h1>
<div class="meta">案號：{d.get('case_no') or '—'}　｜　發文字號：{d.get('doc_no') or '—'}　｜　來源：{os.path.basename(d.get('source_file',''))}</div>
<pre>{body}</pre>
</body></html>"""
            return html
    raise HTTPException(404, "找不到該決定書")


@app.get("/api/reference/{doc_id}", response_class=HTMLResponse)
def reference_full(doc_id: str):
    """函釋 / 判解的完整原文（新視窗開啟）。"""
    r2, r3 = engines()
    for r in r2.refs.docs:
        if str(r.get("doc_id")) == doc_id:
            kind = "行政函釋" if r.get("_kind") == "interpretation" else "司法判解"
            title = r.get("doc_id")
            meta = (f"機關：{r.get('issuing_authority') or r.get('court') or '—'}"
                    f"　｜　字號：{r.get('doc_no') or r.get('case_no') or '—'}"
                    f"　｜　日期：{r.get('doc_date') or '—'}")
            body = (r.get("content") or "").replace("&", "&amp;").replace("<", "&lt;")
            html = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>{title}</title><style>
body{{font-family:'Noto Serif TC',serif;max-width:820px;margin:40px auto;padding:0 24px;
line-height:1.9;color:#1a2b4a;}}
h1{{font-size:17px;border-bottom:3px solid #0b3d91;padding-bottom:10px;color:#0b3d91;}}
.kind{{display:inline-block;background:#ffd400;color:#0b3d91;font-weight:700;
padding:2px 12px;border-radius:12px;font-size:13px;margin-bottom:10px;}}
pre{{white-space:pre-wrap;font-family:inherit;font-size:15px;}}
.meta{{background:#f4f7fc;padding:12px 16px;border-radius:8px;margin:16px 0;font-size:14px;}}
</style></head><body>
<div class="kind">{kind}</div>
<h1>{title}</h1>
<div class="meta">{meta}</div>
<pre>{body}</pre>
</body></html>"""
            return html
    raise HTTPException(404, "找不到該函釋／判解")


# 靜態資源（css/js/圖）
if os.path.isdir(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
