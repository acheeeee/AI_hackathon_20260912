"""可直接人工修改的事實欄位 allowlist。

契約 §2 規定 fact_field 目標只能落在 allowlist 上。計算輸出（例如逾期天數）
不在這裡：依 01 的規則，那要走試算或人工覆核，不能當成可直接改的字串。
"""

FACT_FIELD_ALLOWLIST = frozenset(
    {
        'appellant.name',
        'appellant.address',
        'disposition.authority',
        'disposition.doc_no',
        'disposition.date',
        'service.date',
        'service.method',
        'appeal.filed_date',
        'appeal.received_date',
        'analysis.keywords',
        'analysis.statute_query',
        'disposition.summary',
    }
)


# These fields are shown and edited in the intake-analysis panel. Keep the
# write boundary in one place so a direct API caller cannot bypass the UI's
# maxlength attribute.
ANALYSIS_FIELD_VALUE_MAX_LENGTHS = {
    'analysis.statute_query': 80,
    'analysis.keywords': 120,
    'disposition.summary': 800,
}


# 生成草稿時要把欄位寫成看得懂的中文。前端另有一份顯示用的同名對照
# （frontend/src/utils/factLabels.ts），兩邊要一起改。
FACT_FIELD_LABELS = {
    'appellant.name': '訴願人',
    'appellant.address': '訴願人住所',
    'disposition.authority': '原處分機關',
    'disposition.doc_no': '處分書文號',
    'disposition.date': '處分日期',
    'service.date': '送達日期',
    'service.method': '送達方式',
    'appeal.filed_date': '訴願提起日',
    'appeal.received_date': '訴願收文日',
    'analysis.keywords': '案件相關關鍵字',
    'analysis.statute_query': '建議法規查詢關鍵字',
    'disposition.summary': '行政處分函摘要',
}


def is_allowed_field_path(field_path: str) -> bool:
    return field_path in FACT_FIELD_ALLOWLIST


def fact_field_label(field_path: str) -> str:
    return FACT_FIELD_LABELS.get(field_path, field_path)
