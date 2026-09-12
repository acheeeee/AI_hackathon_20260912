// 對應 backend/src/models.py 與 backend/api.py 回傳的 JSON 結構。
// api.py 目前沒有用到 models.py 的 DraftDecision（那個型別定義了但沒被 draft.py 使用），
// 草稿實際回傳的是 draft.py 的 build_draft() 直接組出的 dict，型別以那份為準。

export interface AppealSummary {
  case_type: string | null
  appellant: string | null
  original_authority: string | null
  disposition_no: string | null
  behavior_date_roc: number | null
  disposition_date_roc: number | null
  facts: string | null
  claims: string | null
}

export interface StatuteRecommendation {
  doc_id: string
  statute_name: string
  article_no: string
  content: string
  score: number
  source: 'statute' | 'interpretation' | 'precedent'
  amend_date: string | null
}

export interface TimelinessAlert {
  triggered: boolean
  message: string
  behavior_date_roc: number | null
  disposition_date_roc: number | null
  changed_statutes: string[]
}

export interface SimilarCase {
  doc_id: string
  source_file: string
  case_type: string | null
  result: string | null
  year: number | null
  summary: string | null
  related_statutes: string[]
  shared_statutes: string[]
  similarity: number
  dimension_scores: Record<string, number>
}

export interface ResultDistributionEntry {
  count: number
  ratio: number
}

export interface ResultDistribution {
  total: number
  distribution: Record<string, ResultDistributionEntry>
}

export interface AnalyzeResponse {
  appeal: AppealSummary
  statutes: StatuteRecommendation[]
  refs: StatuteRecommendation[]
  timeliness: TimelinessAlert
  similar: SimilarCase[]
  distribution: ResultDistribution
  gemini: boolean
}

export interface DraftResult {
  fact: string
  reason: string
  main: string
  mode: 'llm' | 'template'
}

export interface ManualIntakeFields {
  case_type: string
  appellant: string
  original_authority: string
  disposition_no: string
  facts: string
  claims: string
  behavior_date_roc: string
  disposition_date_roc: string
}
