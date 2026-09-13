#!/usr/bin/env python3
"""Generate the two fully fictional Traditional Chinese demo documents.

The documents deliberately mirror the information shape of the repository's
intake samples without reusing their party names, identifiers, dates, or factual
allegations.  Every page is marked as fictional so the files cannot reasonably
be mistaken for an authentic government document.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


OUTPUT_DIR = Path(__file__).resolve().parent
APPEAL_PATH = OUTPUT_DIR / "展示用_虛擬資產服務登記_訴願書.pdf"
DISPOSITION_PATH = OUTPUT_DIR / "展示用_虛擬資產服務登記_行政處分函.pdf"

FONT_REGULAR_PATH = "/System/Library/Fonts/STHeiti Light.ttc"
FONT_BOLD_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_REGULAR = "DemoHeiti"
FONT_BOLD = "DemoHeitiBold"

INK = colors.HexColor("#172033")
MUTED = colors.HexColor("#667085")
LINE = colors.HexColor("#C9D2E3")
PALE_BLUE = colors.HexColor("#EFF5FF")
DEMO_RED = colors.HexColor("#B42318")


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, FONT_REGULAR_PATH, subfontIndex=0))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, FONT_BOLD_PATH, subfontIndex=0))


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName=FONT_BOLD,
            fontSize=22,
            leading=30,
            textColor=INK,
            alignment=TA_CENTER,
            spaceAfter=7 * mm,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base["Normal"],
            fontName=FONT_BOLD,
            fontSize=12,
            leading=18,
            textColor=DEMO_RED,
            alignment=TA_CENTER,
            spaceAfter=5 * mm,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName=FONT_BOLD,
            fontSize=15,
            leading=22,
            textColor=INK,
            alignment=TA_CENTER,
            keepWithNext=True,
            spaceBefore=5 * mm,
            spaceAfter=3 * mm,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName=FONT_BOLD,
            fontSize=12.5,
            leading=19,
            textColor=INK,
            keepWithNext=True,
            spaceBefore=3.5 * mm,
            spaceAfter=1.5 * mm,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=11.3,
            leading=19,
            textColor=INK,
            alignment=TA_JUSTIFY,
            wordWrap="CJK",
            firstLineIndent=0,
            spaceAfter=2.2 * mm,
        ),
        "body_indent": ParagraphStyle(
            "body_indent",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=11.3,
            leading=19,
            textColor=INK,
            alignment=TA_JUSTIFY,
            wordWrap="CJK",
            leftIndent=7 * mm,
            firstLineIndent=-7 * mm,
            spaceAfter=2.2 * mm,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=9.2,
            leading=14,
            textColor=MUTED,
            wordWrap="CJK",
        ),
        "table_label": ParagraphStyle(
            "table_label",
            parent=base["BodyText"],
            fontName=FONT_BOLD,
            fontSize=9.6,
            leading=14,
            textColor=INK,
            alignment=TA_CENTER,
            wordWrap="CJK",
        ),
        "table_value": ParagraphStyle(
            "table_value",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=9.8,
            leading=15,
            textColor=INK,
            wordWrap="CJK",
        ),
        "right": ParagraphStyle(
            "right",
            parent=base["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=11.3,
            leading=19,
            textColor=INK,
            alignment=TA_RIGHT,
            wordWrap="CJK",
        ),
    }


def page_decor(canvas, doc) -> None:  # noqa: ANN001
    width, height = A4
    canvas.saveState()
    canvas.setTitle(doc.title)
    canvas.setAuthor("AI Hackathon demo - fictional material")
    canvas.setSubject("展示用虛構文件；非真實案件，非政府機關公文")
    canvas.setFont(FONT_BOLD, 8.5)
    canvas.setFillColor(DEMO_RED)
    canvas.drawString(18 * mm, height - 12 * mm, "展示用虛構文件｜非真實案件，非政府機關公文")
    canvas.setFillColor(MUTED)
    canvas.setFont(FONT_REGULAR, 8)
    canvas.drawRightString(width - 18 * mm, 10 * mm, f"第 {doc.page} 頁")
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)
    canvas.setStrokeColor(colors.HexColor("#FECACA"))
    canvas.rect(12 * mm, 8 * mm, width - 24 * mm, height - 16 * mm, stroke=1, fill=0)
    canvas.restoreState()


def p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def make_doc(path: Path, title: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=19 * mm,
        leftMargin=19 * mm,
        topMargin=19 * mm,
        bottomMargin=19 * mm,
        title=title,
        author="AI Hackathon demo - fictional material",
        subject="展示用虛構文件；非真實案件，非政府機關公文",
    )


def demo_notice(s: dict[str, ParagraphStyle]) -> Table:
    notice = Table(
        [[p("本文件之當事人、地址、統一編號、文號、日期與事件均為展示目的所虛構；不得作為法律文件或對外行文。", s["small"])]],
        colWidths=[166 * mm],
    )
    notice.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF1F0")),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#FDA29B")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return notice


def build_disposition(s: dict[str, ParagraphStyle]) -> None:
    story = [
        p("金融監督管理委員會　函", s["title"]),
        p("展示用虛構文件", s["subtitle"]),
        demo_notice(s),
        Spacer(1, 5 * mm),
    ]

    metadata = [
        [p("發文日期", s["table_label"]), p("中華民國 115 年 6 月 10 日", s["table_value"])],
        [p("發文字號", s["table_label"]), p("金管證測字第 DEMO1150421 號", s["table_value"])],
        [p("速別", s["table_label"]), p("普通件", s["table_value"])],
        [p("密等", s["table_label"]), p("普通", s["table_value"])],
        [p("附件", s["table_label"]), p("補正項目對照表一份（展示用）", s["table_value"])],
    ]
    meta_table = Table(metadata, colWidths=[30 * mm, 136 * mm])
    meta_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                ("BACKGROUND", (0, 0), (0, -1), PALE_BLUE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend(
        [
            meta_table,
            Spacer(1, 6 * mm),
            p("受文者：星河鏈匯科技股份有限公司（虛構；代表人林語測）", s["body"]),
            p("副本：財團法人中華民國證券櫃檯買賣中心（僅為流程展示）", s["body"]),
            Spacer(1, 2 * mm),
            p("主旨：", s["h2"]),
            p(
                "貴公司申請虛擬資產服務商洗錢防制登記事件，經審核仍有申請書件不完備及記載事項不充分，且經限期補正後仍不能完成補正，依提供虛擬資產服務之事業或人員洗錢防制登記辦法第 5 條第 4 項規定，不予登記，請查照。",
                s["body"],
            ),
            p("說明：", s["h2"]),
            p(
                "一、依洗錢防制法第 6 條及提供虛擬資產服務之事業或人員洗錢防制登記辦法第 5 條規定辦理。",
                s["body_indent"],
            ),
            p(
                "二、貴公司於 115 年 5 月 1 日提出虛擬資產服務商洗錢防制登記申請，申請業務包括虛擬資產交換、移轉及保管服務。本會審查後，以 115 年 5 月 15 日金管證測字第 DEMO1150315 號函通知於文到 14 日內補正；該函於 115 年 5 月 18 日送達，補正期限至 115 年 6 月 1 日止。",
                s["body_indent"],
            ),
            p(
                "三、貴公司於 115 年 5 月 29 日提出補正文件。經核對，交易監控、資訊系統委外、雲端服務治理、私鑰保管及內部稽核等項目，仍有下列資料不足：",
                s["body_indent"],
            ),
            p(
                "（一）交易監控系統僅提出規格書及測試計畫，未提出已完成驗收、警示案件處理流程及門檻參數覆核紀錄，尚難確認是否符合持續監控要求。",
                s["body_indent"],
            ),
            p(
                "（二）用於客戶身分驗證及制裁名單篩檢之外部資料庫，僅記載預定供應商，未附服務範圍、資料來源、更新頻率及中斷時之替代方案。",
                s["body_indent"],
            ),
            p(
                "（三）資訊系統委外與雲端服務部分，未附責任分工矩陣、異常通報時限、營運持續計畫及資料返還與刪除機制。",
                s["body_indent"],
            ),
            p(
                "（四）私鑰保管程序未提出實際授權名冊、多人覆核紀錄及緊急動用後之稽核軌跡。",
                s["body_indent"],
            ),
            p(
                "（五）內部稽核計畫雖列有年度查核項目，但未記載查核頻率、抽樣原則、缺失追蹤期限及向董事會報告之程序。",
                s["body_indent"],
            ),
            p(
                "四、本會認上開事項涉及申請時是否已具備可執行之防制洗錢與資訊安全控制，並非僅屬核准後始得完成之營運準備。貴公司於期限內所提資料仍不足以確認相關控制已可運作，故認定未完成補正。",
                s["body_indent"],
            ),
            p(
                "五、本函為不予登記之行政處分。處分送達資料：115 年 6 月 15 日由郵務送達公司登記營業所，掛號回執展示編號 DEMO-RR-0615。該送達日期僅供本展示案件進行訴願期間試算。",
                s["body_indent"],
            ),
            p(
                "六、如不服本處分，得於本處分達到之次日起 30 日內，繕具訴願書經由本會向行政院提起訴願。",
                s["body_indent"],
            ),
            Spacer(1, 5 * mm),
            p("正本：星河鏈匯科技股份有限公司（虛構）", s["body"]),
            p("副本：財團法人中華民國證券櫃檯買賣中心（流程展示）", s["body"]),
            Spacer(1, 8 * mm),
            p("主任委員　展示用署名", s["right"]),
        ]
    )
    doc = make_doc(DISPOSITION_PATH, "展示用虛構行政處分函")
    doc.build(story, onFirstPage=page_decor, onLaterPages=page_decor)


def party_table(s: dict[str, ParagraphStyle]) -> LongTable:
    data = [
        [
            p("稱謂", s["table_label"]),
            p("姓名或法人名稱", s["table_label"]),
            p("住所、居所或營業所", s["table_label"]),
            p("身分證明文件字號", s["table_label"]),
        ],
        [
            p("訴願人", s["table_label"]),
            p("星河鏈匯科技股份有限公司<br/><font color='#B42318'>（展示用虛構法人）</font>", s["table_value"]),
            p("臺北市示範區測試路 100 號 8 樓<br/>（虛構地址）", s["table_value"]),
            p("統一編號：<br/>00000000<br/>（展示編碼）", s["table_value"]),
        ],
        [
            p("代表人", s["table_label"]),
            p("林語測（虛構姓名）", s["table_value"]),
            p("同訴願人營業所", s["table_value"]),
            p("不適用", s["table_value"]),
        ],
        [
            p("訴願代理人", s["table_label"]),
            p("未委任", s["table_value"]),
            p("不適用", s["table_value"]),
            p("不適用", s["table_value"]),
        ],
    ]
    table = LongTable(data, colWidths=[23 * mm, 52 * mm, 58 * mm, 33 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.55, LINE),
                ("BACKGROUND", (0, 0), (-1, 0), PALE_BLUE),
                ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#F8FAFC")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def build_appeal(s: dict[str, ParagraphStyle]) -> None:
    story = [
        p("訴願書", s["title"]),
        p("展示用虛構文件", s["subtitle"]),
        demo_notice(s),
        Spacer(1, 5 * mm),
        party_table(s),
        Spacer(1, 5 * mm),
    ]

    disposition_data = [
        [p("原行政處分機關", s["table_label"]), p("金融監督管理委員會", s["table_value"])],
        [p("受理訴願機關", s["table_label"]), p("行政院", s["table_value"])],
        [
            p("行政處分書<br/>發文日期及文號", s["table_label"]),
            p("中華民國 115 年 6 月 10 日<br/>金管證測字第 DEMO1150421 號", s["table_value"]),
        ],
        [
            p("行政處分之年月日", s["table_label"]),
            p("中華民國 115 年 6 月 10 日", s["table_value"]),
        ],
    ]
    disposition_table = Table(disposition_data, colWidths=[50 * mm, 116 * mm])
    disposition_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.55, LINE),
                ("BACKGROUND", (0, 0), (0, -1), PALE_BLUE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend(
        [
            disposition_table,
            Spacer(1, 5 * mm),
            p("本訴願事件有無提起教師申訴程序：無（本案非教師申訴事件）", s["small"]),
            p("訴願請求事項", s["h1"]),
            p(
                "一、撤銷原行政處分機關 115 年 6 月 10 日金管證測字第 DEMO1150421 號不予登記處分。",
                s["body_indent"],
            ),
            p(
                "二、請命原行政處分機關於二個月內，就訴願人之申請另為適法之處分；如認仍有事實待釐清，請給予陳述意見及補充資料之機會。",
                s["body_indent"],
            ),
            p("事 實：", s["h1"]),
            p(
                "一、訴願人為籌設中之虛擬資產服務事業，於 115 年 5 月 1 日向原行政處分機關申請虛擬資產服務商洗錢防制登記，申請業務包括虛擬資產交換、移轉及保管服務。訴願人於登記完成前尚未對外招攬或提供服務。",
                s["body_indent"],
            ),
            p(
                "二、原行政處分機關於 115 年 5 月 15 日以金管證測字第 DEMO1150315 號函通知補正，列出交易監控、外部資料庫、資訊系統委外、雲端服務、私鑰保管及內部稽核等事項，命於文到 14 日內補正。該補正通知於 115 年 5 月 18 日送達，期限至 115 年 6 月 1 日止。",
                s["body_indent"],
            ),
            p(
                "三、訴願人於 115 年 5 月 29 日提出補正，檢附交易監控測試計畫、外部資料庫服務說明、雲端責任分工矩陣、私鑰多人覆核流程及年度稽核計畫。訴願人並說明，部分正式驗收紀錄及實際警示案件紀錄，須於完成登記、系統正式上線後始能產生。",
                s["body_indent"],
            ),
            p(
                "四、原行政處分機關仍以申請書件不完備、記載事項不充分及限期補正後不能完成補正為由，依提供虛擬資產服務之事業或人員洗錢防制登記辦法第 5 條第 4 項作成不予登記處分。該處分於 115 年 6 月 15 日以郵務送達訴願人登記營業所，掛號回執展示編號為 DEMO-RR-0615。",
                s["body_indent"],
            ),
            p(
                "五、訴願人於 115 年 7 月 7 日以本書狀向原行政處分機關提出訴願，距送達日未逾 30 日。本訴願自始以書面提出，並非先以言詞、電子郵件或其他方式表示不服後再補送書面。",
                s["body_indent"],
            ),
            p("理 由：", s["h1"]),
            p(
                "一、洗錢防制法第 6 條要求虛擬資產服務事業完成洗錢防制登記後始得提供服務。訴願人正因遵守該限制，於取得登記前只進行籌備、測試及契約協商，未以真實客戶資料營運。若要求申請人於依法不得營業之階段，提出必須由正式營運才能產生之交易警示、處理紀錄及正式驗收軌跡，即可能形成不登記不得營業、未營業又無法證明正式運作之循環。",
                s["body_indent"],
            ),
            p(
                "二、訴願人並非未回應補正通知。115 年 5 月 29 日所送資料逐項對應原行政處分機關列示事項，已提出可在籌備階段完成之制度文件、測試紀錄與契約責任配置。原處分如認其中仍有不足，應具體指出何一申請要件欠缺、何一文件內容無法補足，以及何以不得採取附條件、限期改善或再次陳述意見等較小侵害手段。",
                s["body_indent"],
            ),
            p(
                "三、行政程序法第 7 條所揭示之比例原則，要求行政行為採取有助於目的達成、侵害較少且利益衡量不失均衡之手段。本案直接不予登記，將使已投入人員、系統與合規建置之申請人無法繼續推進驗收；相較之下，限期提出第三方測試報告、限制特定業務範圍或要求分階段查核，均可能達成監理目的而侵害較小。原處分未說明為何上述手段不可採，理由尚有不足。",
                s["body_indent"],
            ),
            p(
                "四、關於交易監控與外部資料庫，訴願人已提出供應商服務規格、資料來源類型、更新頻率、警示分級、案件覆核及替代方案；關於資訊系統委外與雲端服務，已提出責任分工矩陣、通報時限、備援及退出計畫；關於私鑰保管與內部稽核，亦已提出多人授權、操作留痕、抽樣與缺失追蹤流程。原處分僅概稱資料不足，未具體回應前開補正內容。",
                s["body_indent"],
            ),
            p(
                "五、提供虛擬資產服務之事業或人員洗錢防制登記辦法第 5 條第 4 項之適用，仍應以申請書件確有不完備、記載不充分，且經限期補正仍不能完成為前提。訴願人已於期限內補正，爭議在於補正內容是否足以證明申請時之制度準備，而非單純逾期未補正。原處分應就各項法定要件、所欠資料與補正內容逐一比對，始足使訴願人理解判斷基礎。",
                s["body_indent"],
            ),
            p(
                "六、綜上，原處分對於洗錢防制登記之申請要件、限期補正之完成程度、比例原則及較小侵害手段，均有重新審酌之必要。為此請撤銷原處分，命原行政處分機關就訴願人所提資料另為適法處分。",
                s["body_indent"],
            ),
            p("程序審查補充聲明（供展示流程核對）", s["h1"]),
            p(
                "一、本書狀載明訴願人、代表人、原行政處分機關、受理訴願機關、處分日期與文號、訴願請求、事實及理由，並由代表人簽署；如認格式仍可補正，訴願人願於通知期限內補正。",
                s["body_indent"],
            ),
            p(
                "二、原處分於 115 年 6 月 15 日送達，本訴願於 115 年 7 月 7 日以書面提出；訴願人未曾依訴願法第 57 條但書先以其他方式表示不服，故無補送書面日期。",
                s["body_indent"],
            ),
            p(
                "三、訴願人即為原處分之受文者，係依法設立之股份有限公司，具有訴願能力；代表人林語測依公司登記資料代表訴願人。",
                s["body_indent"],
            ),
            p(
                "四、據訴願人所知，原處分目前尚未由原行政處分機關撤銷或廢止；本事件此前未經訴願決定，亦未曾撤回後重行提起。",
                s["body_indent"],
            ),
            p(
                "五、系爭函明確對訴願人之洗錢防制登記申請作成不予登記決定，直接發生不得取得登記之法律效果，訴願人以該行政處分為救濟標的。",
                s["body_indent"],
            ),
            p("檢附之證據或附件：", s["h1"]),
            p("一、115 年 6 月 10 日行政處分函影本一份。", s["body_indent"]),
            p("二、115 年 6 月 15 日送達回執影本一份（展示編號 DEMO-RR-0615）。", s["body_indent"]),
            p("三、115 年 5 月 15 日補正通知函影本一份。", s["body_indent"]),
            p("四、115 年 5 月 29 日補正文件及附件目錄一份。", s["body_indent"]),
            p("五、交易監控與雲端服務責任分工對照表一份。", s["body_indent"]),
            Spacer(1, 6 * mm),
            p("此　致", s["h2"]),
            p("金融監督管理委員會　轉陳", s["body"]),
            p("行政院", s["body"]),
            Spacer(1, 6 * mm),
            p("訴 願 人：星河鏈匯科技股份有限公司", s["right"]),
            p("代 表 人：林語測（展示用簽署）", s["right"]),
            p("中 華 民 國 115 年 7 月 7 日", s["right"]),
            Spacer(1, 6 * mm),
            p(
                "聲明：本訴願自始以書面提出。副本於 115 年 7 月 7 日送交原行政處分機關。本文所有姓名、編號、地址、日期、附件與事實均屬虛構。",
                s["small"],
            ),
        ]
    )
    doc = make_doc(APPEAL_PATH, "展示用虛構訴願書")
    doc.build(story, onFirstPage=page_decor, onLaterPages=page_decor)


def main() -> None:
    register_fonts()
    s = styles()
    build_disposition(s)
    build_appeal(s)
    print(DISPOSITION_PATH)
    print(APPEAL_PATH)


if __name__ == "__main__":
    main()
