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
