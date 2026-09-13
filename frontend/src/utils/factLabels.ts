// FACT_FIELD_ALLOWLIST（backend/caseapi/domain/fact_fields.py）欄位的中文標籤。
// 兩邊要同步改；這裡只是顯示用，不影響後端驗證。
export const FACT_FIELD_LABELS: Record<string, string> = {
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
  'disposition.summary': '行政處分函摘要',
  'analysis.statute_query': '建議法規查詢詞',
  'appeal.form_defect': '訴願書是否欠缺法定程式',
  'appeal.defect_remediable': '訴願書程式欠缺是否可補正',
  'appeal.correction_scope': '本次訴願補正通知的範圍',
  'appeal.correction_notified': '是否已通知限期補正',
  'appeal.correction_deadline': '訴願補正期限',
  'appeal.correction_completed': '是否已完成通知範圍內的補正',
  'appeal.correction_date': '完成訴願補正日期',
  'appeal.initial_submission_method': '最初提出訴願的方式',
  'appeal.objection_date': '向機關作成不服表示日期',
  'appeal.written_submission_completed': '是否已補送訴願書',
  'appeal.written_submission_date': '補送訴願書日期',
  'disposition.recipient': '原處分相對人',
  'appellant.standing': '訴願人資格',
  'appellant.entity_type': '訴願人類型',
  'appellant.capacity': '是否具備訴願能力',
  'legal_representative.present': '是否由法定代理人代為訴願',
  'representative.name': '代表人或管理人姓名',
  'representative.authority': '是否由有權代表人或管理人為訴願行為',
  'disposition.current_status': '原行政處分目前狀態',
  'case.prior_decision_record': '同一事件是否已有訴願決定',
  'case.prior_withdrawal_record': '同一事件是否曾撤回訴願',
  'challenged_act.type': '被爭執事項的法律性質',
  'challenged_act.within_appeal_scope': '是否屬訴願救濟範圍',
}

export function factFieldLabel(path: string): string {
  return FACT_FIELD_LABELS[path] ?? path
}

const FACT_ORIGIN_LABELS: Record<string, string> = {
  program: '自動擷取',
  human: '人工填寫',
  ai: 'AI 生成',
  llm: '自動分析',
  merged: '合併結果',
}

export function factOriginLabel(origin: string): string {
  return FACT_ORIGIN_LABELS[origin] ?? origin
}

export const PROCESSING_STATUS_LABELS: Record<string, string> = {
  unprocessed: '未處理',
  processing: '處理中',
  completed: '已完成',
}

export const PROCESSING_STATUS_TAG_TYPE: Record<string, 'info' | 'warning' | 'success'> = {
  unprocessed: 'info',
  processing: 'warning',
  completed: 'success',
}

export const PROCEDURAL_REVIEW_STATUS_LABELS: Record<string, string> = {
  insufficient_data: '缺送達日期，無法試算',
  deadline_known_filing_unknown: '已知期限，待補訴願提起日',
  within_period: '期間內',
  overdue: '逾期',
}

export const PROCEDURAL_REVIEW_STATUS_TAG_TYPE: Record<
  string,
  'info' | 'warning' | 'success' | 'danger'
> = {
  insufficient_data: 'info',
  deadline_known_filing_unknown: 'warning',
  within_period: 'success',
  overdue: 'danger',
}
