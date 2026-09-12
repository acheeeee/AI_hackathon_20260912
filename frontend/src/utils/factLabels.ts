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
}

export function factFieldLabel(path: string): string {
  return FACT_FIELD_LABELS[path] ?? path
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
