"""
新北市訴願管理 AI 系統 — Streamlit Demo（四頁籤）
啟動：
    cd app
    pip install -r requirements.txt
    streamlit run app.py

左側上傳訴願書 PDF 或貼上文字；右側四頁籤：
  1. 資訊擷取與分類
  2. 適用法規與時效提示
  3. 歷史相似前例（前 3-5 名）
  4. 決定書草稿預覽與匯出
"""
from __future__ import annotations
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st

from src.intake import parse_incoming, parse_incoming_pdf
from src.recommend import Stage2Recommender
from src.similar import Stage3SimilarCases
from src.draft import build_draft
from src.providers import get_provider
from src.parsers import extract_text


st.set_page_config(page_title="新北市訴願管理 AI 系統", layout="wide")


@st.cache_resource
def load_engines():
    return Stage2Recommender(), Stage3SimilarCases()


@st.cache_data(show_spinner=False)
def _read_pdf(file_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(file_bytes)
        path = tmp.name
    try:
        text, _ = extract_text(path)
    finally:
        os.unlink(path)
    return text


def main():
    st.title("⚖️ 新北市訴願管理 AI 輔助系統")
    prov = get_provider()
    api_status = "🟢 Gemini 已連線（向量檢索＋草稿生成啟用）" if prov.available \
        else "🟡 未設定 API key（降級為 BM25 檢索＋模板草稿）"
    st.caption(api_status)

    # ---------- 側欄：輸入 ----------
    with st.sidebar:
        st.header("📥 進件")
        up = st.file_uploader("上傳訴願書 PDF", type=["pdf"])
        st.markdown("— 或 —")
        pasted = st.text_area("貼上訴願書全文", height=200)
        use_llm = st.checkbox("使用 LLM 補強爭點擷取／草稿（耗用額度）", value=False)
        run = st.button("🚀 開始分析", type="primary", use_container_width=True)

    if run:
        if up is not None:
            text = _read_pdf(up.read())
        elif pasted.strip():
            text = pasted
        else:
            st.warning("請上傳 PDF 或貼上訴願書文字。")
            return
        st.session_state["appeal"] = parse_incoming(text, use_llm=use_llm)
        st.session_state["use_llm"] = use_llm

    appeal = st.session_state.get("appeal")
    if not appeal:
        st.info("請於左側上傳訴願書 PDF 或貼上文字，再按「開始分析」。")
        return

    r2, r3 = load_engines()
    use_llm = st.session_state.get("use_llm", False)

    tab1, tab2, tab3, tab4 = st.tabs([
        "1️⃣ 資訊擷取與分類", "2️⃣ 適用法規與時效提示",
        "3️⃣ 歷史相似前例", "4️⃣ 決定書草稿",
    ])

    # ===== 頁籤1 =====
    with tab1:
        st.subheader("案件自動分類")
        st.success(f"案件類型：{appeal.case_type or '（未能自動判定，請確認）'}")
        c1, c2 = st.columns(2)
        with c1:
            st.text_input("訴願人", appeal.appellant or "", key="f_appellant")
            st.text_input("原處分機關", appeal.original_authority or "", key="f_auth")
            st.text_input("原處分書文號", appeal.disposition_no or "", key="f_dispno")
        with c2:
            appeal.behavior_date_roc = st.number_input(
                "行為時（民國年）", value=int(appeal.behavior_date_roc or 0), step=1)
            appeal.disposition_date_roc = st.number_input(
                "處分時（民國年）", value=int(appeal.disposition_date_roc or 0), step=1)
        st.text_area("違規事實摘要", appeal.facts or "", height=120)
        st.text_area("訴願人主張／爭點", appeal.claims or "", height=100)

    # ===== 頁籤2 =====
    with tab2:
        st.subheader("智能法規推薦")
        recs = r2.recommend_statutes(appeal, top_k=6)
        st.session_state["recs"] = recs
        for s in recs:
            with st.expander(f"📖 {s.statute_name} {s.article_no}　(分數 {s.score})"):
                st.write(s.content)
                if s.amend_date:
                    st.caption(f"修正日期：{s.amend_date}")
        st.markdown("**相關函釋 / 判解**")
        for x in r2.recommend_refs(appeal, top_k=3):
            st.markdown(f"- [{'函釋' if x.source=='interpretation' else '判解'}] "
                        f"{x.doc_id}　({x.score})")

        st.divider()
        st.subheader("⏱️ 從新從輕時效提示（行政罰法第5條）")
        alert = r2.timeliness_alert(appeal, recs)
        st.session_state["alert"] = alert
        if alert.triggered:
            st.error(alert.message)
        else:
            st.info(alert.message)

    # ===== 頁籤3 =====
    with tab3:
        st.subheader("歷史相似前例（前 5 名）")
        recs = st.session_state.get("recs") or r2.recommend_statutes(appeal, top_k=6)
        sims = r3.find_similar(appeal, top_k=5, recommended_statutes=recs)
        st.session_state["sims"] = sims
        dist = r3.result_distribution(sims)
        st.session_state["dist"] = dist

        if dist.get("distribution"):
            cols = st.columns(len(dist["distribution"]))
            for col, (res, info) in zip(cols, dist["distribution"].items()):
                col.metric(res, f"{int(info['ratio']*100)}%", f"{info['count']} 件")

        for i, c in enumerate(sims, 1):
            shared = "；".join(c.shared_statutes) if c.shared_statutes else "無共同實體法條"
            with st.expander(f"{i}. {c.year}年 ｜ {c.case_type} ｜ 結果：{c.result} "
                             f"（相似度 {c.similarity}）"):
                st.success(f"🔗 與本案共同法條：{shared}")
                st.write("**維度分數**（法條重疊為主）：", c.dimension_scores)
                if c.related_statutes:
                    st.write("**該案完整引用法條**：", "；".join(c.related_statutes[:6]))
                st.caption(f"來源：{os.path.basename(c.source_file)}")

    # ===== 頁籤4 =====
    with tab4:
        st.subheader("決定書草稿")
        if st.button("📝 生成草稿"):
            recs = st.session_state.get("recs", [])
            sims = st.session_state.get("sims", [])
            alert = st.session_state.get("alert")
            dist = st.session_state.get("dist")
            with st.spinner("生成中…"):
                draft = build_draft(appeal, recs, sims, alert, dist, use_llm=use_llm)
            st.session_state["draft"] = draft

        draft = st.session_state.get("draft")
        if draft:
            mode = "LLM 三段論生成" if draft["mode"] == "llm" else "模板（未用 LLM）"
            st.caption(f"生成方式：{mode}")
            body = (
                "新北市政府訴願決定書（草稿）\n"
                "════════════════════\n\n"
                f"【主　文】\n{draft['main']}\n\n"
                f"【事　實】\n{draft['fact']}\n\n"
                f"【理　由】\n{draft['reason']}\n"
            )
            st.text_area("草稿內容", body, height=460)
            st.download_button("⬇️ 匯出草稿 (.txt)", body,
                               file_name="訴願決定書草稿.txt", mime="text/plain")
            st.warning("本草稿由 AI 輔助生成，法條均來自知識庫原文；仍須承辦人審核確認後定稿。")


if __name__ == "__main__":
    main()
