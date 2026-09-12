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
    }
)


def is_allowed_field_path(field_path: str) -> bool:
    return field_path in FACT_FIELD_ALLOWLIST
