"""
決定書草稿生成（階段一延伸/加分項）。
設計原則（zero hallucination）：
  - 事實欄：模板填空，用擷取的結構化欄位，不讓 LLM 自由生成。
  - 理由欄：LLM 依法律三段論撰寫，但大前提（法規）只能來自「推薦法規的知識庫原文」。
    prompt 中明確提供法條原文，並要求不得引用未提供的法條。
  - 無 API key 時：全部走模板，理由欄列出推薦法條原文 + 相似案例傾向，供承辦人補寫。
"""
from __future__ import annotations
from typing import Optional

from .models import IncomingAppeal, StatuteRecommendation, SimilarCase, TimelinessAlert
from .providers import get_provider


def _facts_section(appeal: IncomingAppeal) -> str:
    appellant = appeal.appellant or "○○○"
    authority = appeal.original_authority or "原處分機關"
    disp = appeal.disposition_no or "（處分書文號）"
    case_type = appeal.case_type or "違規事件"
    facts = appeal.facts or "（請補充違規事實）"
    return (
        f"緣訴願人{appellant}因{case_type}，不服{authority}所為之處分"
        f"（{disp}），提起訴願。事實摘要如下：\n{facts}"
    )


def _statutes_block(statutes: list[StatuteRecommendation]) -> str:
    lines = []
    for s in statutes:
        if s.source == "statute":
            lines.append(f"{s.statute_name}{s.article_no}：「{s.content.strip()}」")
    return "\n".join(lines)


def build_draft(appeal: IncomingAppeal,
                statutes: list[StatuteRecommendation],
                similar: list[SimilarCase],
                alert: Optional[TimelinessAlert] = None,
                result_dist: Optional[dict] = None,
                use_llm: bool = True) -> dict:
    """回傳 {'fact': ..., 'reason': ..., 'main': ..., 'mode': 'llm'|'template'}。"""
    fact = _facts_section(appeal)
    statutes_text = _statutes_block(statutes)

    # 相似案例傾向
    tendency = ""
    if result_dist and result_dist.get("distribution"):
        top = max(result_dist["distribution"].items(), key=lambda kv: kv[1]["count"])
        tendency = f"歷史相似案件中，{top[0]}佔 {int(top[1]['ratio']*100)}%（共{result_dist['total']}件）。"

    prov = get_provider()
    if use_llm and prov.available and statutes_text:
        try:
            alert_text = alert.message if (alert and alert.triggered) else "本案無新舊法變更之從新從輕爭點。"
            prompt = (
                "你是新北市政府訴願審議承辦人。請直接撰寫訴願決定書的「理由」欄正文，"
                "使用繁體中文、公文體，依法律三段論（法規→本案涵攝→結論）行文。\n\n"
                "【撰寫規範（僅供你遵循，切勿寫進輸出）】\n"
                "- 大前提只能引用下方提供的法條原文，不得引用未提供的任何法條或函釋。\n"
                "- 小前提須結合本案事實與訴願人主張進行涵攝分析。\n"
                "- 結論須明確（訴願駁回／原處分撤銷／不受理其一）。\n"
                "- 不得杜撰法條字號、判例或事實。\n"
                "- 只輸出理由欄公文正文本身，不要輸出任何說明、標題、檢查清單、"
                "markdown 標記或關於你自己思考過程的文字。\n\n"
                f"【本案事實】\n{fact}\n\n"
                f"【訴願人主張】\n{appeal.claims or '（未提供）'}\n\n"
                f"【可引用之法條原文（僅限這些）】\n{statutes_text}\n\n"
                f"【新舊法提示】\n{alert_text}\n\n"
                f"【歷史相似案件傾向（僅供參考，不得作為唯一依據）】\n{tendency}\n\n"
                "理由欄正文："
            )
            reason = _clean_llm_output(prov.generate(prompt, temperature=0.2, max_tokens=2048))
            main = _infer_main(reason)
            return {"fact": fact, "reason": reason.strip(), "main": main, "mode": "llm"}
        except Exception as e:
            print(f"[draft] LLM 生成失敗，降級模板：{str(e)[:80]}")

    # 模板降級
    reason_lines = ["一、按下列規定：", statutes_text or "（請補充適用法規）",
                    "\n二、本案分析：", f"訴願人主張：{appeal.claims or '（略）'}",
                    "（請承辦人依上開法規涵攝本案事實補充分析）"]
    if alert and alert.triggered:
        reason_lines.append(f"\n三、{alert.message}")
    if tendency:
        reason_lines.append(f"\n（參考）{tendency}")
    return {"fact": fact, "reason": "\n".join(reason_lines),
            "main": "（請承辦人確認主文）", "mode": "template"}


def _infer_main(reason: str) -> str:
    if "撤銷" in reason[-200:]:
        return "原處分撤銷。"
    if "不受理" in reason[-200:]:
        return "訴願不受理。"
    if "駁回" in reason[-200:] or "無理由" in reason[-200:]:
        return "訴願駁回。"
    return "（請承辦人確認主文）"


def _clean_llm_output(text: str) -> str:
    """清除 LLM 可能外洩的指令/檢查清單/markdown 雜訊，只保留公文正文。"""
    import re
    if not text:
        return ""
    lines = text.split("\n")
    out = []
    # 觸發詞：出現即視為模型開始自我檢查/輸出後設內容，截斷其後
    stop_markers = ("Review against", "strict constraint", "constraints",
                    "以下是我的", "檢查清單", "checklist", "let me ", "I will ",
                    "作為承辦人，我", "（僅供你遵循", "撰寫規範")
    for ln in lines:
        if any(m.lower() in ln.lower() for m in stop_markers):
            break
        out.append(ln)
    cleaned = "\n".join(out)
    # 去除 markdown 粗體/標題符號
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"(?m)^#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*[-*]\s+", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
