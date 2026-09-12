"""Extracting the 事實／理由 narrative from a 訴願書, for use as the default
BM25 query when suggesting relevant statutes (see 選法規 / statute_search).

The top-matter table (稱謂/姓名/...) and the closing formalities
(檢附之證據或附件、此致、簽名) are pure boilerplate with no legal-relevant
vocabulary; the 事實 and 理由 sections are where the actual dispute and any
cited statute names/articles live, so that's the useful search text.
"""

from caseapi.domain.appeal_extraction import extract_case_narrative

# Real extracted text (via PyMuPDF) from
# data/raw/訴願書予行政處分函-1/案01_金管會不予洗錢防制登記_1155000434__訴願書.pdf.
SAMPLE_WITH_EVIDENCE_SECTION = """訴願請求事項：
請求撤銷原處分，並准予虛擬資產服務商洗錢防制登記。
事 實：
訴願人於114年3月31日申請洗錢防制登記，經補正後，原處分機關仍以申請書件不完備
、逾期不能完成補正為由，於114年7月24日以金管證券字第1140140639號函不予登記。
理 由：
一、依洗錢防制法第6條第1項規定，未完成登記前不得從事虛擬資產服務業務，訴願人
為守法計，於核准前僅維持必要籌備架構，尚無法先行聘足人員及完成平台上線。
二、原處分機關以人員未到齊、平台未完成、監控系統未建置為由不予登記。
檢附之證據或附件：
一、原行政處分書影本乙份。
此 致
金融監督管理委員會 轉陳
行政院
訴 願 人：絕○○○股份有限公司"""

# Real extracted text from
# 案04_環保署噪音管制區劃定作業準則_1100168552__訴願書.pdf — no "訴願請求事項"
# preamble immediately before 事實 the same way, and only one numbered claim.
SAMPLE_WITHOUT_EVIDENCE_LABEL = """事 實：
行政院環境保護署於109年8月5日以環署空字第1090057114A號令，修正發布「噪音管制
區劃定作業準則」第5條、第7條及第12條。
理 由：
一、上開修正將鄰近高速公路土地之管制分貝，由39分貝放寬至67至74分貝。
此 致
行政院環境保護署 轉陳"""


def test_extracts_fact_and_reason_sections_up_to_the_evidence_label() -> None:
    narrative = extract_case_narrative(SAMPLE_WITH_EVIDENCE_SECTION)

    assert narrative is not None
    assert '洗錢防制法第6條第1項' in narrative
    assert '未完成登記前不得從事虛擬資產服務業務' in narrative
    # 「事實：」之前的請求事項、之後的表頭與結尾格式都不該混進來
    assert '請求撤銷原處分' not in narrative
    assert '訴願人：' not in narrative
    assert '轉陳' not in narrative


def test_falls_back_to_stopping_before_this_zhi_when_no_evidence_label() -> None:
    narrative = extract_case_narrative(SAMPLE_WITHOUT_EVIDENCE_LABEL)

    assert narrative is not None
    assert '噪音管制區劃定作業準則' in narrative
    assert '轉陳' not in narrative


def test_missing_fact_section_returns_none_not_the_whole_document() -> None:
    narrative = extract_case_narrative('完全沒有事實理由段落的文字')

    assert narrative is None
