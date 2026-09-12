"""
決定書草稿 Word (.docx) 匯出。
產生正式格式的「新北市政府訴願決定書（草稿）」，含主文/事實/理由三段。
"""
from __future__ import annotations
import io

from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH


def build_docx(draft: dict, appeal_meta: dict | None = None) -> bytes:
    """
    draft: {'main':..., 'fact':..., 'reason':..., 'mode':...}
    appeal_meta: 可選 {'case_type','appellant','original_authority','disposition_no'}
    回傳 .docx 的位元組。
    """
    doc = Document()

    # 預設字型（中文用標楷體/新細明體，Word 常用公文字型）
    style = doc.styles["Normal"]
    style.font.name = "DFKai-SB"
    style.font.size = Pt(12)

    # 標題
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("新北市政府訴願決定書（草稿）")
    run.bold = True
    run.font.size = Pt(16)

    # 生成方式註記
    mode = "AI 三段論生成" if draft.get("mode") == "llm" else "模板產生（未使用 AI）"
    note = doc.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    nr = note.add_run(f"（本草稿由系統輔助{mode}，僅供承辦人審核參考）")
    nr.italic = True
    nr.font.size = Pt(9)
    nr.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

    # 案件基本資料（若有）
    if appeal_meta:
        doc.add_paragraph()
        for label, key in [("案件類型", "case_type"), ("訴願人", "appellant"),
                            ("原處分機關", "original_authority"), ("原處分書文號", "disposition_no")]:
            val = appeal_meta.get(key)
            if val:
                p = doc.add_paragraph()
                p.add_run(f"{label}：").bold = True
                p.add_run(str(val))

    def section(heading: str, body: str):
        doc.add_paragraph()
        h = doc.add_paragraph()
        hr = h.add_run(heading)
        hr.bold = True
        hr.font.size = Pt(13)
        for line in (body or "").split("\n"):
            para = doc.add_paragraph(line)
            para.paragraph_format.first_line_indent = Pt(24)
            para.paragraph_format.line_spacing = 1.5

    section("主　文", draft.get("main", ""))
    section("事　實", draft.get("fact", ""))
    section("理　由", draft.get("reason", ""))

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()
