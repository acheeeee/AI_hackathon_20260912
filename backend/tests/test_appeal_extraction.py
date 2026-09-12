"""Rule-based field extraction from a fixed-format 訴願書 (appeal letter).

The 訴願書 is a standardized Executive Yuan form; PyMuPDF's default text
order jumbles the top table (labels all come first, then values, because
that is how the form's cells are laid out), so extraction anchors on the
clean signature-line restatement near the bottom ("訴 願 人：NAME") and on
the "原行政處分機關 / 受理訴願機關" and "發文日期及文號 / 行政處分之年月日"
label pairs, which stay intact across every sample this was calibrated on.

Fields that cannot be read reliably from the appeal letter alone (address,
service date/method) are deliberately left unextracted — see
docs/協作設計/06 §5.2: the appeal letter is fixed-format so rule-based
extraction is appropriate, but guessing at a low-confidence field is worse
than leaving it for human fact-editing via PATCH /facts.
"""

from caseapi.domain.appeal_extraction import extract_appeal_fields

# Real extracted text (via PyMuPDF) from
# data/raw/訴願書予行政處分函-1/案01_金管會不予洗錢防制登記_1155000434__訴願書.pdf,
# trimmed to the parts extraction actually reads.
SAMPLE_1_COMPANY = """訴願書
稱 謂
姓 名
（或法人、團體名稱
）
出生年月
日
住 所 或 居 所
（營業所或事務所）
身分證明文件字
號
訴 願 人絕○○○股份有限公
司
○○市○○區○○路○段
○○號
統一編號：○○
○○○○○○
代 表 人
（法人
或團體
應填具
）
林○○
原行政處分機關
金融監督管理委員會
受理訴願機關
行政院
行政處分書
發文日期及文號
114年7月24日金管證券字第11
40140639號函
行政處分之年
月日
中華民國114年7
月24日
本訴願事件（專任教師或準用教師者）有無提起教師申訴程序：
訴願請求事項：
請求撤銷原處分，並准予虛擬資產服務商洗錢防制登記。
此 致
金融監督管理委員會 轉陳
行政院
訴 願 人：絕○○○股份有限公司
代 表 人：林○○（簽名或蓋章）
中 華 民 國 114年8月○○日
副本已於 年 月 日抄送原行政處分機關"""

# Same shape, individual filer (no representative), real signature date present
# (unlike the anonymized mock samples where the day is redacted with ○○).
SAMPLE_INDIVIDUAL_WITH_REAL_DATE = """訴 願 人吳○銨
原行政處分機關
行政院環境保護署
受理訴願機關
行政院
行政處分書
發文日期及文號
109年8月5日環署空字第10900
57114A號令
行政處分之年
月日
中華民國109年8
月5日
本訴願事件（專任教師或準用教師者）有無提起教師申訴程序：
此 致
行政院環境保護署 轉陳
行政院
訴 願 人：吳○銨
中 華 民 國 109年9月3日
副本已於 年 月 日抄送原行政處分機關"""


def test_extracts_appellant_name_from_the_clean_signature_line() -> None:
    fields = extract_appeal_fields(SAMPLE_1_COMPANY)

    assert fields['appellant.name'] == '絕○○○股份有限公司'


def test_extracts_disposition_authority_between_its_label_pair() -> None:
    fields = extract_appeal_fields(SAMPLE_1_COMPANY)

    assert fields['disposition.authority'] == '金融監督管理委員會'


def test_extracts_disposition_doc_no_despite_mid_number_line_wrap() -> None:
    fields = extract_appeal_fields(SAMPLE_1_COMPANY)

    assert fields['disposition.doc_no'] == '金管證券字第1140140639號'


def test_extracts_disposition_date_as_gregorian_iso_from_roc_date() -> None:
    fields = extract_appeal_fields(SAMPLE_1_COMPANY)

    assert fields['disposition.date'] == '2025-07-24'


def test_does_not_guess_fields_it_cannot_read_reliably() -> None:
    fields = extract_appeal_fields(SAMPLE_1_COMPANY)

    assert fields['appellant.address'] is None
    assert fields['service.date'] is None
    assert fields['service.method'] is None


def test_redacted_filing_day_in_mock_data_yields_none_not_a_guess() -> None:
    fields = extract_appeal_fields(SAMPLE_1_COMPANY)

    assert fields['appeal.filed_date'] is None


def test_extracts_real_filing_date_when_it_is_not_redacted() -> None:
    fields = extract_appeal_fields(SAMPLE_INDIVIDUAL_WITH_REAL_DATE)

    assert fields['appellant.name'] == '吳○銨'
    assert fields['disposition.authority'] == '行政院環境保護署'
    assert fields['disposition.doc_no'] == '環署空字第1090057114A號'
    assert fields['appeal.filed_date'] == '2020-09-03'


def test_extract_appeal_fields_only_returns_allowlisted_field_paths() -> None:
    from caseapi.domain.fact_fields import is_allowed_field_path

    fields = extract_appeal_fields(SAMPLE_1_COMPANY)

    assert fields
    for path in fields:
        assert is_allowed_field_path(path), path


def test_empty_text_extracts_nothing() -> None:
    fields = extract_appeal_fields('')

    assert all(value is None for value in fields.values())
