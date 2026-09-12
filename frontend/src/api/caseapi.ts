// 新後端（caseapi，/api/v1/*）的 client。走 vite.config.ts 的 /api/v1 proxy；
// 舊後端的 client 在 client.ts，兩邊互不共用狀態，逐步把畫面從舊換到新。

const BASE = '/api/v1'

export class CaseApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public status: number,
  ) {
    super(message)
  }
}

interface ApiErrorBody {
  code: string
  message: string
  details: Record<string, unknown>
  retryable: boolean
}

interface Envelope<T> {
  success: boolean
  data: T | null
  error: ApiErrorBody | null
}

function newIdempotencyKey(): string {
  return crypto.randomUUID()
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init)
  const body = (await res.json()) as Envelope<T>
  if (!res.ok || !body.success || body.data === null) {
    throw new CaseApiError(
      body.error?.message ?? res.statusText,
      body.error?.code ?? 'UNKNOWN',
      res.status,
    )
  }
  return body.data
}

export type ProcessingStatus = 'unprocessed' | 'processing' | 'completed'

export interface CaseSummary {
  case_id: string
  title: string | null
  official_case_no: string | null
  workflow_state: string
  processing_status: ProcessingStatus
  case_revision: number
  created_at: string
  updated_at: string
}

export type ResourceHead = { revision_id: string; kind: string; freshness: string }

export interface CaseDetail extends CaseSummary {
  active_heads: Record<string, ResourceHead>
}

export async function listCases(): Promise<CaseSummary[]> {
  const data = await request<{ items: CaseSummary[]; next_cursor: string | null }>('/cases')
  return data.items
}

export async function getCase(caseId: string): Promise<CaseDetail> {
  return request<CaseDetail>(`/cases/${encodeURIComponent(caseId)}`)
}

export type ExtractedFields = Record<string, string | null>

export interface IntakeResult {
  case_id: string
  case_revision: number
  extracted_fields: ExtractedFields
}

export async function intakeCase(params: {
  appealPdf: File
  dispositionPdf?: File
  title?: string
}): Promise<IntakeResult> {
  const form = new FormData()
  form.set('appeal_pdf', params.appealPdf)
  if (params.dispositionPdf) form.set('disposition_pdf', params.dispositionPdf)
  if (params.title) form.set('title', params.title)
  return request<IntakeResult>('/cases/intake', {
    method: 'POST',
    body: form,
    headers: { 'Idempotency-Key': newIdempotencyKey() },
  })
}

export interface FactFieldValue {
  value: string | null
  origin: string
  human_asserted: boolean
  reason: string
  source: unknown
  updated_by: string
  updated_at: string
}

export async function getFacts(caseId: string): Promise<Record<string, FactFieldValue>> {
  const data = await request<{ fields: Record<string, FactFieldValue> }>(
    `/cases/${encodeURIComponent(caseId)}/facts`,
  )
  return data.fields
}

export interface PatchFactsResult {
  case_revision: number
  fields: Record<string, FactFieldValue>
}

export async function patchFacts(params: {
  caseId: string
  expectedCaseRevision: number
  reason: string
  fieldPath: string
  value: string
}): Promise<PatchFactsResult> {
  return request<PatchFactsResult>(`/cases/${encodeURIComponent(params.caseId)}/facts`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': newIdempotencyKey() },
    body: JSON.stringify({
      expected_case_revision: params.expectedCaseRevision,
      reason: params.reason,
      field_changes: [
        {
          field_path: params.fieldPath,
          value: params.value,
          human_asserted: true,
          reason: params.reason,
        },
      ],
    }),
  })
}

// ---------- 程序審查（訴願法第14條期間試算，未經法律覆核） ----------

export type ProceduralReviewStatus =
  | 'insufficient_data'
  | 'deadline_known_filing_unknown'
  | 'within_period'
  | 'overdue'

export interface ProceduralReview {
  case_id: string
  status: ProceduralReviewStatus
  deadline_date: string | null
  days_from_deadline: number | null
  missing_fields: string[]
  statute_basis: string
  caveats: string[]
  legal_review_status: string
}

export async function getProceduralReview(caseId: string): Promise<ProceduralReview> {
  return request<ProceduralReview>(
    `/cases/${encodeURIComponent(caseId)}/procedural-review`,
  )
}

export interface CaseDocument {
  document_id: string
  document_role: 'appeal' | 'disposition'
  source_filename: string
  source_sha256: string
  page_count: number
  created_at: string
}

export async function listDocuments(caseId: string): Promise<CaseDocument[]> {
  const data = await request<{ items: CaseDocument[] }>(
    `/cases/${encodeURIComponent(caseId)}/documents`,
  )
  return data.items
}

export function documentContentUrl(caseId: string, documentId: string): string {
  return `${BASE}/cases/${encodeURIComponent(caseId)}/documents/${encodeURIComponent(documentId)}/content`
}

// ---------- 側邊欄 AI 對話 ----------
// 後端契約見 backend/caseapi/schemas/chat.py、routes_chat.py、routes_runs.py。
// intent 目前只有 verify（自由提問，走真的 BM25 檢索＋開原文）與
// explain（解釋一個選取的目標，目前前端只支援 fact_field 目標）。

export type ChatIntent = 'verify' | 'explain'
export type RunState =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'needs_input'

export interface ChatMessage {
  message_id: string
  case_id: string
  thread_id: string
  role: 'user' | 'assistant'
  content: string
  intent: string | null
  target: FactFieldTarget | Record<string, unknown> | null
  run_id: string | null
  created_at: string
}

export interface FactFieldTarget {
  kind: 'fact_field'
  resource_id: string
  resource_revision: string
  field_path: string
}

export async function createThread(caseId: string, title?: string): Promise<string> {
  const data = await request<{ thread_id: string }>(
    `/cases/${encodeURIComponent(caseId)}/chat-threads`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': newIdempotencyKey() },
      body: JSON.stringify({ title: title ?? null }),
    },
  )
  return data.thread_id
}

export async function listMessages(caseId: string, threadId: string): Promise<ChatMessage[]> {
  const data = await request<{ items: ChatMessage[] }>(
    `/cases/${encodeURIComponent(caseId)}/chat-threads/${encodeURIComponent(threadId)}/messages`,
  )
  return data.items
}

export interface SendMessageResult {
  message_id: string
  run_id: string
  state: RunState
  case_revision: number
}

export async function sendMessage(params: {
  caseId: string
  threadId: string
  expectedCaseRevision: number
  content: string
  intent: ChatIntent
  target?: FactFieldTarget
}): Promise<SendMessageResult> {
  return request<SendMessageResult>(
    `/cases/${encodeURIComponent(params.caseId)}/chat-threads/${encodeURIComponent(params.threadId)}/messages`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': newIdempotencyKey() },
      body: JSON.stringify({
        expected_case_revision: params.expectedCaseRevision,
        content: params.content,
        intent: params.intent,
        target: params.target ?? null,
        annotation_refs: [],
      }),
    },
  )
}

export interface RunDetail {
  run_id: string
  case_id: string
  kind: string
  state: RunState
  error: { code: string; type: string } | null
  created_at: string
  updated_at: string
}

export async function getRun(caseId: string, runId: string): Promise<RunDetail> {
  return request<RunDetail>(
    `/cases/${encodeURIComponent(caseId)}/runs/${encodeURIComponent(runId)}`,
  )
}

export interface RunEvent {
  sequence: number
  event_type: string
  tool_call_id: string | null
  timestamp: string
  payload: Record<string, unknown>
}

export async function getRunEvents(caseId: string, runId: string): Promise<RunEvent[]> {
  const data = await request<{ items: RunEvent[] }>(
    `/cases/${encodeURIComponent(caseId)}/runs/${encodeURIComponent(runId)}/events`,
  )
  return data.items
}

export interface EvidenceDetail {
  evidence_id: string
  source_ref: {
    document_id: string
    kb_release_id: string | null
    source_spans: Array<{ page: number; line: number; char_start: number; char_end: number }>
  }
  quote: string | null
  source_exists: boolean
  quote_matches: boolean
  support_status: string
  assessed_by: string
  temporal_status: string
}

export async function getEvidence(caseId: string, evidenceId: string): Promise<EvidenceDetail> {
  return request<EvidenceDetail>(
    `/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(evidenceId)}`,
  )
}
