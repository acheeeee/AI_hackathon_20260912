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
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()

  // randomUUID is restricted to secure contexts and is therefore absent when
  // the single-host demo is opened through its plain-HTTP Elastic IP.
  // getRandomValues remains available there and lets us build an RFC 4122 v4
  // identifier without falling back to predictable Math.random values.
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6]! & 0x0f) | 0x40
  bytes[8] = (bytes[8]! & 0x3f) | 0x80
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-')
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
export type IntakeAnalysisStatus =
  | 'offline'
  | 'online_completed'
  | 'online_failed_fallback'

export interface IntakeResult {
  case_id: string
  case_revision: number
  extracted_fields: ExtractedFields
  analysis_status: IntakeAnalysisStatus
  analysis_error: string | null
}

export async function intakeCase(params: {
  appealPdf: File
  dispositionPdf?: File
  title?: string
  consentToOnlineAnalysis?: boolean
}): Promise<IntakeResult> {
  const form = new FormData()
  form.set('appeal_pdf', params.appealPdf)
  if (params.dispositionPdf) form.set('disposition_pdf', params.dispositionPdf)
  if (params.title) form.set('title', params.title)
  if (params.consentToOnlineAnalysis) form.set('consent_to_online_analysis', 'true')
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
  legal_review_status?: 'not_reviewed'
}

export async function getFacts(caseId: string): Promise<Record<string, FactFieldValue>> {
  const data = await request<{ fields: Record<string, FactFieldValue> }>(
    `/cases/${encodeURIComponent(caseId)}/facts`,
  )
  return data.fields
}

export interface PatchFactsResult {
  case_revision: number
  resource_revision?: string
  fields: Record<string, FactFieldValue>
}

export interface FactChangeInput {
  fieldPath: string
  value: string | null
}

type PatchFactsParams = {
  caseId: string
  expectedCaseRevision: number
  reason: string
} & (FactChangeInput | { fieldChanges: FactChangeInput[] })

export async function patchFacts(params: PatchFactsParams): Promise<PatchFactsResult> {
  const changes = 'fieldChanges' in params ? params.fieldChanges : [params]
  return request<PatchFactsResult>(`/cases/${encodeURIComponent(params.caseId)}/facts`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': newIdempotencyKey() },
    body: JSON.stringify({
      expected_case_revision: params.expectedCaseRevision,
      reason: params.reason,
      field_changes: changes.map((change) => ({
        field_path: change.fieldPath,
        value: change.value,
        human_asserted: true,
        reason: params.reason,
      })),
    }),
  })
}

// ---------- 程序審查（訴願法第77條八款，未經法律覆核） ----------

export type ProceduralReviewStatus =
  'insufficient_data' | 'deadline_known_filing_unknown' | 'within_period' | 'overdue'

export interface ProceduralReview {
  case_id: string
  case_revision?: number
  status: ProceduralReviewStatus
  deadline_date: string | null
  days_from_deadline: number | null
  missing_fields: string[]
  statute_basis: string
  caveats: string[]
  legal_review_status: string
  clause_assessments?: Article77ClauseAssessment[]
  field_definitions?: ProceduralFieldDefinition[]
}

export interface ProceduralFieldDefinition {
  field_path: string
  label: string
  input_type: 'select' | 'date' | 'text'
  options: { value: string; label: string }[]
  help_text?: string
}

export interface ProceduralInputSource {
  origin: string
  reason: string
  source: unknown
}

export type Article77Outcome =
  'NOT_TRIGGERED' | 'TRIGGERED' | 'NOT_APPLICABLE' | 'INSUFFICIENT_EVIDENCE' | 'NEEDS_HUMAN'

export type Article77EvaluationMode = 'rule' | 'mock' | 'manual_review'

export interface Article77ClauseAssessment {
  clause_no: number
  rule_id: string
  input: Record<string, unknown>
  missing_fields?: string[]
  input_sources?: Record<string, ProceduralInputSource>
  status: Article77Outcome
  rule_description: string
  reason: string
  evaluation_mode: Article77EvaluationMode
}

export async function getProceduralReview(caseId: string): Promise<ProceduralReview> {
  return request<ProceduralReview>(`/cases/${encodeURIComponent(caseId)}/procedural-review`)
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

export type ChatIntent = 'verify' | 'explain' | 'revise_selection'
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
  target: TargetRef | Record<string, unknown> | null
  run_id: string | null
  created_at: string
}

export interface FactFieldTarget {
  kind: 'fact_field'
  resource_id: string
  resource_revision: string
  field_path: string
}

export interface DraftBlockTarget {
  kind: 'draft_block'
  resource_id: string
  resource_revision: string
  block_id: string
  char_start: number
  char_end: number
  selected_text: string
  selected_text_sha256: string
}

export type TargetRef = FactFieldTarget | DraftBlockTarget

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
  target?: TargetRef
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

export interface ProviderConfig {
  provider: string
  model?: string
  region?: string
}

export interface RunDetail {
  run_id: string
  case_id: string
  kind: string
  state: RunState
  proposal_ids: string[]
  // 後端 run_service._serialize_run 一直有回傳這個（provider／model／region，
  // 不含憑證）。前端要顯示「這個答案是哪個模型給的」，否則後端退回固定假模型
  // 時畫面上看不出來，使用者只會以為 AI 壞了。
  provider_config?: ProviderConfig
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

// ---------- 選法規：對 r3 做 BM25 搜尋、保存人工挑選結果 ----------

export interface StatuteHit {
  chunk_id: string
  document_id: string
  section_id: string
  statute_name: string | null
  article_key: string | null
  excerpt: string
  score: number
  why_relevant?: string | null
  full_text?: string | null
  official_url?: string | null
}

export interface StatuteSearchResult {
  query_used: string | null
  suggested_query?: string | null
  hits: StatuteHit[]
}

export async function searchStatutes(
  caseId: string,
  query?: string,
): Promise<StatuteSearchResult> {
  const params = query ? `?${new URLSearchParams({ q: query }).toString()}` : ''
  return request<StatuteSearchResult>(
    `/cases/${encodeURIComponent(caseId)}/statute-search${params}`,
  )
}

export interface SelectedStatute {
  chunk_id: string
  document_id: string
  section_id: string
  statute_name: string
  article_key: string
  excerpt: string
}

export async function getStatuteSelection(caseId: string): Promise<SelectedStatute[]> {
  const data = await request<{ selected: SelectedStatute[] }>(
    `/cases/${encodeURIComponent(caseId)}/statute-selection`,
  )
  return data.selected
}

// ---------- 草稿生成：POST 後背景跑 run，結果是提案不是正文 ----------
// 舊的階段 A fixture `POST /cases/{id}/drafts` 已標成 deprecated，前端不呼叫。

export interface DraftGenerationStarted {
  run_id: string
  state: RunState
  draft_id: string
  draft_resource_revision: string
  case_revision: number
}

export async function startDraftGeneration(params: {
  caseId: string
  expectedCaseRevision: number
  instruction?: string
}): Promise<DraftGenerationStarted> {
  return request<DraftGenerationStarted>(
    `/cases/${encodeURIComponent(params.caseId)}/draft-generations`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': newIdempotencyKey() },
      body: JSON.stringify({
        expected_case_revision: params.expectedCaseRevision,
        instruction: params.instruction ?? null,
      }),
    },
  )
}

export interface ProposalBlock {
  block_id: string
  text: string
  citations: string[]
}

export interface ProposalChangeGroup {
  id: string
  change_class: string
  reason: string
  evidence_ids: string[]
  operations: Array<{ op: string; after_blocks?: ProposalBlock[]; after_value?: string }>
}

export interface ProposalDetail {
  proposal_id: string
  origin: string
  run_id: string | null
  mode: string
  state: string
  base_case_revision: number
  applied_group_ids: string[]
  change_groups: ProposalChangeGroup[]
}

export async function getProposal(caseId: string, proposalId: string): Promise<ProposalDetail> {
  return request<ProposalDetail>(
    `/cases/${encodeURIComponent(caseId)}/proposals/${encodeURIComponent(proposalId)}`,
  )
}

export interface MergeConflict {
  code: string
  resource_id?: string
  block_id?: string
  details?: Record<string, unknown>
}

export interface MergePreview {
  preview_id: string
  proposal_id: string
  current_case_revision: number
  selected_group_ids: string[]
  preview_hash: string
  conflicts: MergeConflict[]
  missing_group_dependencies: Array<Record<string, unknown>>
  unverified_evidence_ids: string[]
  diffs: Array<Record<string, unknown>>
  can_apply: boolean
}

export async function createMergePreview(params: {
  caseId: string
  proposalId: string
  expectedCaseRevision: number
  selectedGroupIds: string[]
}): Promise<MergePreview> {
  return request<MergePreview>(
    `/cases/${encodeURIComponent(params.caseId)}/proposals/${encodeURIComponent(params.proposalId)}/merge-previews`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': newIdempotencyKey() },
      body: JSON.stringify({
        expected_case_revision: params.expectedCaseRevision,
        selected_group_ids: params.selectedGroupIds,
      }),
    },
  )
}

export interface ProposalApplication {
  applied_group_ids: string[]
  case_revision: number
  resulting_case_revision: number
  resource_revisions: Record<string, string>
  invalidated_resources: string[]
  unverified_evidence_ids: string[]
  proposal_state: string
}

export async function applyProposal(params: {
  caseId: string
  proposalId: string
  expectedCaseRevision: number
  previewId: string
  previewHash: string
  acceptedGroupIds: string[]
}): Promise<ProposalApplication> {
  return request<ProposalApplication>(
    `/cases/${encodeURIComponent(params.caseId)}/proposals/${encodeURIComponent(params.proposalId)}/applications`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': newIdempotencyKey() },
      body: JSON.stringify({
        expected_case_revision: params.expectedCaseRevision,
        preview_id: params.previewId,
        preview_hash: params.previewHash,
        accepted_group_ids: params.acceptedGroupIds,
      }),
    },
  )
}

export async function rejectProposal(params: {
  caseId: string
  proposalId: string
  reason: string
}): Promise<ProposalDetail> {
  return request<ProposalDetail>(
    `/cases/${encodeURIComponent(params.caseId)}/proposals/${encodeURIComponent(params.proposalId)}/rejections`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': newIdempotencyKey() },
      body: JSON.stringify({ reason: params.reason }),
    },
  )
}

export interface DraftResourceContent {
  draft_kind: string
  title: string | null
  blocks: ProposalBlock[]
}

export interface DraftResource {
  resource_id: string
  resource_kind: 'draft'
  resource_revision: string
  parent_revision: string | null
  origin: string
  content: DraftResourceContent
  content_hash: string
  dependencies: Record<string, unknown>
  is_head: boolean
  freshness: string | null
  created_by: string
  created_at: string
}

export async function getDraftResource(caseId: string, draftId: string): Promise<DraftResource> {
  return request<DraftResource>(
    `/cases/${encodeURIComponent(caseId)}/resources/${encodeURIComponent(draftId)}`,
  )
}

export interface DraftPatchResult {
  draft_id: string
  resource_revision: string
  parent_revision: string
  case_revision: number
  freshness: string
  blocks: ProposalBlock[]
}

export async function patchDraftBlock(params: {
  caseId: string
  draftId: string
  expectedCaseRevision: number
  baseResourceRevision: string
  block: ProposalBlock
}): Promise<DraftPatchResult> {
  return request<DraftPatchResult>(
    `/cases/${encodeURIComponent(params.caseId)}/drafts/${encodeURIComponent(params.draftId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': newIdempotencyKey() },
      body: JSON.stringify({
        expected_case_revision: params.expectedCaseRevision,
        base_resource_revision: params.baseResourceRevision,
        block_changes: [params.block],
      }),
    },
  )
}

const DEFAULT_DRAFT_PDF_FILENAME = 'appeal-decision-draft.pdf'

export async function downloadDraftPdf(params: {
  caseId: string
  draftId: string
}): Promise<void> {
  const response = await fetch(
    `${BASE}/cases/${encodeURIComponent(params.caseId)}/drafts/${encodeURIComponent(params.draftId)}/pdf`,
    { headers: { Accept: 'application/pdf' } },
  )
  if (!response.ok) {
    let body: Envelope<never> | null = null
    try {
      body = (await response.json()) as Envelope<never>
    } catch {
      // A proxy or gateway may replace the normal API envelope.  Keep the
      // fallback intentionally generic so response bodies never reach the UI.
    }
    throw new CaseApiError(
      body?.error?.message ?? '無法產生草稿 PDF',
      body?.error?.code ?? 'PDF_EXPORT_FAILED',
      response.status,
    )
  }
  const contentType = response.headers.get('Content-Type')?.toLowerCase() ?? ''
  if (!contentType.startsWith('application/pdf')) {
    throw new CaseApiError('伺服器未回傳 PDF', 'PDF_EXPORT_FAILED', 502)
  }

  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = _safePdfFilename(response.headers.get('Content-Disposition'))
  anchor.hidden = true
  document.body.append(anchor)
  try {
    anchor.click()
  } finally {
    anchor.remove()
    URL.revokeObjectURL(objectUrl)
  }
}

function _safePdfFilename(contentDisposition: string | null): string {
  const candidate = contentDisposition?.match(/filename="([^"\r\n]+)"/i)?.[1]
  if (!candidate || !/^[A-Za-z0-9._-]+\.pdf$/i.test(candidate) || candidate.includes('..')) {
    return DEFAULT_DRAFT_PDF_FILENAME
  }
  return candidate
}

export async function saveStatuteSelection(params: {
  caseId: string
  expectedCaseRevision: number
  reason: string
  selected: SelectedStatute[]
}): Promise<{ case_revision: number; selected: SelectedStatute[] }> {
  return request(`/cases/${encodeURIComponent(params.caseId)}/statute-selection`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': newIdempotencyKey() },
    body: JSON.stringify({
      expected_case_revision: params.expectedCaseRevision,
      reason: params.reason,
      selected: params.selected,
    }),
  })
}
