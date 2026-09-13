"""Shared editable facts and typed validation for procedural review."""

from __future__ import annotations

from datetime import date
import re
from typing import Any


def _select(path: str, label: str, options: tuple[tuple[str, str], ...], help_text: str = ''):
    return {'field_path': path, 'label': label, 'input_type': 'select',
            'options': [{'value': value, 'label': text} for value, text in options],
            'help_text': help_text}


def _date(path: str, label: str, help_text: str = ''):
    return {'field_path': path, 'label': label, 'input_type': 'date',
            'options': [], 'help_text': help_text}


def _text(path: str, label: str, help_text: str = ''):
    return {'field_path': path, 'label': label, 'input_type': 'text',
            'options': [], 'help_text': help_text}


_YES_NO = (('yes', '是'), ('no', '否'))
_YES_NO_UNCERTAIN = (*_YES_NO, ('uncertain', '尚需法律判斷'))

PROCEDURAL_FIELD_DEFINITIONS: tuple[dict[str, Any], ...] = (
    _select('appeal.form_defect', '訴願書是否欠缺法定程式', _YES_NO,
            '僅指訴願程序的書面要件；原申請案的補件要求不屬於本欄。'),
    _select('appeal.defect_remediable', '訴願書程式欠缺是否可補正', _YES_NO),
    _select('appeal.correction_scope', '本次訴願補正通知的範圍', (
        ('form', '訴願書程式'), ('capacity', '訴願能力／法定代理人'),
        ('representation', '團體代表人／管理人'), ('all', '以上缺漏全部涵蓋')),
        '請依訴願程序的補正通知確認，不適用原行政處分前的申請補件。'),
    _select('appeal.correction_notified', '是否已通知限期補正', _YES_NO),
    _date('appeal.correction_deadline', '訴願補正期限'),
    _select('appeal.correction_completed', '是否已完成通知範圍內的補正', _YES_NO),
    _date('appeal.correction_date', '完成訴願補正日期'),
    _date('service.date', '行政處分送達日期', '不能以發文日期或收文號中的日期替代。'),
    _date('appeal.received_date', '訴願收文日', '機關實際收受訴願書的日期，優先於提起日。'),
    _date('appeal.filed_date', '訴願提起日', '缺收文日才使用；請確認不是單純簽署日期。'),
    _select('appeal.initial_submission_method', '最初提出訴願的方式', (
        ('written', '已提出訴願書'), ('objection', '先作不服表示，後補訴願書'))),
    _date('appeal.objection_date', '向機關作成不服表示日期'),
    _select('appeal.written_submission_completed', '是否已補送訴願書', _YES_NO),
    _date('appeal.written_submission_date', '補送訴願書日期', '自不服表示起三十日內補送，無須等候通知。'),
    _text('appellant.name', '訴願人'),
    _text('disposition.recipient', '原處分相對人'),
    _select('appellant.standing', '訴願人資格', (
        ('recipient', '處分相對人'), ('interested', '法律上利害關係人'),
        ('not_eligible', '不符合第18條資格'), ('uncertain', '尚需法律判斷'))),
    _select('appellant.entity_type', '訴願人類型', (
        ('individual', '自然人'), ('legal_person', '法人'),
        ('other_group', '非法人團體'), ('local_government', '地方自治團體'))),
    _select('appellant.capacity', '是否具備訴願能力', (
        ('capable', '具備訴願能力'), ('incapable', '欠缺訴願能力'),
        ('uncertain', '尚需法律判斷'))),
    _select('legal_representative.present', '是否由法定代理人代為訴願', _YES_NO),
    _text('representative.name', '代表人或管理人姓名'),
    _select('representative.authority', '是否由有權代表人或管理人為訴願行為', _YES_NO_UNCERTAIN),
    _text('disposition.doc_no', '原處分文號'),
    _select('disposition.current_status', '原行政處分目前狀態', (
        ('exists', '仍存在'), ('revoked', '已撤銷且已不存在'),
        ('abolished', '已廢止且已不存在'), ('nonexistent', '因其他原因已不存在'),
        ('uncertain', '尚需法律判斷'))),
    _select('case.prior_decision_record', '同一事件是否已有訴願決定', _YES_NO,
            '請確認本案是否對同一事件再次提起；未查得資料不等於沒有紀錄。'),
    _select('case.prior_withdrawal_record', '同一事件是否曾撤回訴願', _YES_NO),
    _select('challenged_act.type', '被爭執事項的法律性質', (
        ('administrative_disposition', '行政處分'), ('non_administrative', '非行政處分'),
        ('uncertain', '尚需法律判斷'))),
    _select('challenged_act.within_appeal_scope', '是否屬訴願救濟範圍', _YES_NO_UNCERTAIN),
)

PROCEDURAL_FIELD_BY_PATH = {
    descriptor['field_path']: descriptor for descriptor in PROCEDURAL_FIELD_DEFINITIONS
}


def validate_procedural_field_value(field_path: str, value: str | None) -> None:
    """Reject unsupported enums, invalid dates and non-string values at write boundaries."""
    descriptor = PROCEDURAL_FIELD_BY_PATH.get(field_path)
    if descriptor is None or value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f'{field_path} 必須為文字或空值')
    if descriptor['input_type'] == 'select':
        if value not in {option['value'] for option in descriptor['options']}:
            raise ValueError(f'{field_path} 不是有效選項')
    elif descriptor['input_type'] == 'date':
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) is None:
            raise ValueError(f'{field_path} 必須使用 YYYY-MM-DD 日期格式')
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f'{field_path} 不是有效日期') from exc
    elif len(value) > 500:
        raise ValueError(f'{field_path} 不得超過 500 字')
