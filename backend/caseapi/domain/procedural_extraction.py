"""Extract explicit procedural statements with exact source spans, never defaults.

These are document assertions for preliminary review, not independently verified
facts. Silence, conditional statements and conflicting values remain unresolved.
Application-stage correction is deliberately outside this extractor's scope.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

_DATE = r'(?:中華民國|民國)?(?P<year>\d{2,4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日'
_UNCERTAIN = re.compile(
    r'假設|倘若|如果|若|如認|未確認|尚未確認|是否|可能|例如|請求|請認定|'
    r'未見|不能確認|無法確認|尚待|待確認|存疑|別案|他案|其他案件|引述|引用'
)

# All patterns anchor on a statement about this appeal/disposition. Do not match
# bare legal vocabulary (e.g. a request to revoke is not an already-revoked act).
_STATEMENTS: tuple[tuple[str, str, str], ...] = (
    ('appeal.initial_submission_method', 'written', r'(?:本訴願|訴願人)(?:自始)?以書面提出'),
    ('appeal.initial_submission_method', 'objection', r'(?:本訴願|訴願人)先以(?:言詞|電子郵件|其他方式)表示不服'),
    ('appeal.form_defect', 'no', r'(?:本訴願書|訴願書)(?:已確認)?符合法定程式'),
    ('appeal.form_defect', 'yes', r'(?:本訴願書|訴願書)不合法定程式'),
    ('appeal.defect_remediable', 'yes', r'訴願書(?:程式|格式)瑕疵可以補正'),
    ('appeal.defect_remediable', 'no', r'訴願書(?:程式|格式)瑕疵不能補正'),
    ('appellant.standing', 'recipient', r'訴願人(?:即|亦)?為(?:原處分|本處分)之(?:受文者|相對人)'),
    ('appellant.capacity', 'capable', r'訴願人(?:即為原處分之受文者[，,])?(?:係依法設立之(?:股份有限公司|有限公司|法人)[，,])?具有訴願能力'),
    ('appellant.capacity', 'incapable', r'訴願人(?:不具有|無)訴願能力'),
    ('legal_representative.present', 'yes', r'本訴願已由法定代理人代為提出'),
    ('legal_representative.present', 'no', r'本訴願未由法定代理人代為提出'),
    ('representative.authority', 'yes', r'代表人[^。；，,]{1,30}依公司登記資料代表訴願人'),
    ('representative.authority', 'no', r'本訴願未由代表人或管理人提出'),
    ('disposition.current_status', 'exists', r'原處分(?:目前)?(?:仍然存在|仍有效|尚未(?:由原行政處分機關)?撤銷或廢止)'),
    ('disposition.current_status', 'revoked', r'原處分(?:目前)?已(?:經)?(?:由原行政處分機關)?撤銷(?=[。；，,]|$)'),
    ('disposition.current_status', 'abolished', r'原處分(?:目前)?已(?:經)?(?:由原行政處分機關)?廢止(?=[。；，,]|$)'),
    ('disposition.current_status', 'nonexistent', r'原處分(?:目前)?已不存在'),
    ('case.prior_decision_record', 'no', r'(?:本事件|本訴願事件|同一訴願事件)(?:此前|先前)?未(?:經|有)訴願決定'),
    ('case.prior_decision_record', 'yes', r'(?:本事件|本訴願事件|同一訴願事件)(?:此前|先前)已(?:經|有)訴願決定'),
    ('case.prior_withdrawal_record', 'no', r'(?:本事件|本訴願事件|同一訴願事件)(?:此前)?未曾撤回(?:後重行提起)?'),
    ('case.prior_withdrawal_record', 'no', r'(?:本事件|本訴願事件|同一訴願事件)[^。；]{0,40}[，,]亦未曾撤回(?:後重行提起)?'),
    ('case.prior_withdrawal_record', 'yes', r'(?:本事件|本訴願事件)(?:此前)?(?:已|曾)撤回後重行提起'),
    ('challenged_act.type', 'administrative_disposition', r'本函為[^。；]{0,30}之行政處分'),
    ('challenged_act.type', 'non_administrative', r'(?:系爭函|本函|被爭執行為)(?:並)?非行政處分'),
    ('challenged_act.within_appeal_scope', 'yes', r'本案屬(?:於)?訴願救濟範圍'),
    ('challenged_act.within_appeal_scope', 'no', r'本案(?:依法)?不屬(?:於)?訴願救濟範圍'),
)


def extract_procedural_fields(text: str, *, document_role: str) -> dict[str, dict[str, Any]]:
    """Return recognized values and quote spans into the original extracted text."""
    offsets = [index for index, char in enumerate(text) if not char.isspace()]
    compact = ''.join(text[index] for index in offsets)
    candidates: dict[str, list[dict[str, Any]]] = {}

    def add(path: str, value: str | None, match: re.Match[str]) -> None:
        if value is None or _is_uncertain(compact, match.start()):
            return
        if path == 'disposition.current_status' and value in ('revoked', 'abolished'):
            if re.search(r'部分|一部|僅|尚未生效|未生效', _sentence(compact, match.start())):
                return
        start, end = offsets[match.start()], offsets[match.end() - 1] + 1
        candidates.setdefault(path, []).append({
            'value': value, 'quote': text[start:end], 'start': start, 'end': end,
        })

    for path, value, pattern in _STATEMENTS:
        for match in re.finditer(pattern, compact):
            add(path, value, match)

    service_pattern = (
        r'(?:原處分|該處分|本處分)(?:送達日期[：:]|於)' + _DATE +
        r'(?:以郵務|以郵寄|由郵務)?送達|處分送達資料[：:]' +
        _DATE.replace('?P<year>', '?P<year2>').replace('?P<month>', '?P<month2>').replace('?P<day>', '?P<day2>') +
        r'由郵務送達'
    )
    for match in re.finditer(service_pattern, compact):
        add('service.date', _date_value(match), match)
        if '郵務' in match.group():
            add('service.method', '郵務送達', match)

    for path, prefix in (
        ('appeal.received_date', r'(?:原行政處分機關|受理訴願機關)於'),
        ('appeal.objection_date', r'訴願人於'),
        ('appeal.written_submission_date', r'訴願人於'),
    ):
        suffix = {
            'appeal.received_date': r'(?:收受|收訖)訴願書',
            'appeal.objection_date': r'(?:以言詞|以電子郵件)?表示不服',
            'appeal.written_submission_date': r'補送訴願書',
        }[path]
        for match in re.finditer(prefix + _DATE + suffix, compact):
            add(path, _date_value(match), match)
            if path == 'appeal.written_submission_date':
                add('appeal.written_submission_completed', 'yes', match)

    if document_role == 'appeal':
        for match in re.finditer(r'訴願人[：:]([\u4e00-\u9fffA-Za-z0-9]{2,60}?(?:股份有限公司|有限公司))', compact):
            add('appellant.entity_type', 'legal_person', match)
        for match in re.finditer(r'代表人(?P<name>[\u4e00-\u9fff]{2,8})依公司登記資料代表訴願人', compact):
            add('representative.name', match.group('name'), match)
    if document_role == 'disposition':
        for match in re.finditer(r'受文者[：:]([^（(，,。；：:]{2,60})(?=[（(，,。；：:])', compact):
            add('disposition.recipient', match.group(1), match)
        # A remedy instruction supplies the document's asserted remedy, not the
        # appellant's actual filing method or a finding on legal jurisdiction.
        for match in re.finditer(r'如不服本處分，得[^。；]{0,90}提起訴願', compact):
            add('challenged_act.within_appeal_scope', 'yes', match)

    return {path: _resolve(items) for path, items in candidates.items()}


def _is_uncertain(text: str, start: int) -> bool:
    return bool(_UNCERTAIN.search(_sentence(text, start)))


def _sentence(text: str, start: int) -> str:
    sentence_start = max(text.rfind(mark, 0, start) for mark in '。；!?！？') + 1
    ends = [end for mark in '。；!?！？' if (end := text.find(mark, start)) >= 0]
    return text[sentence_start:min(ends) if ends else len(text)]


def _date_value(match: re.Match[str]) -> str | None:
    groups = match.groupdict()
    suffix = '' if groups.get('year') is not None else '2'
    year_text = groups.get('year' + suffix)
    if year_text is None:
        return None
    year = int(year_text)
    if len(year_text) < 4:
        year += 1911
    try:
        return date(year, int(groups['month' + suffix]), int(groups['day' + suffix])).isoformat()
    except ValueError:
        return None


def _resolve(items: list[dict[str, Any]]) -> dict[str, Any]:
    if len({item['value'] for item in items}) == 1:
        return items[0]
    return {**items[0], 'value': None, 'conflict': True, 'candidates': items}
