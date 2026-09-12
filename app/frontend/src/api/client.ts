import type { AnalyzeResponse, DraftResult, ManualIntakeFields } from '@/types/appeal'

// 開發環境走 vite.config.ts 的 proxy（/api -> http://localhost:8000），production
// 由部署時的反向代理或 CORS 設定決定；前端一律只打相對路徑 /api/*。
const BASE = '/api'

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
  }
}

async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json()
    return body.detail ?? res.statusText
  } catch {
    return res.statusText
  }
}

export async function checkHealth(): Promise<{ status: string; gemini: boolean }> {
  const res = await fetch(`${BASE}/health`)
  if (!res.ok) throw new ApiError(await parseErrorDetail(res), res.status)
  return res.json()
}

export type AnalyzeMode = 'pdf' | 'manual' | 'text'

export interface AnalyzeParams {
  mode: AnalyzeMode
  useLlm: boolean
  pdf?: File
  text?: string
  manual?: ManualIntakeFields
}

export async function analyzeAppeal(params: AnalyzeParams): Promise<AnalyzeResponse> {
  const form = new FormData()
  form.set('mode', params.mode)
  form.set('use_llm', String(params.useLlm))
  if (params.text) form.set('text', params.text)
  if (params.pdf) form.set('pdf', params.pdf)
  if (params.manual) {
    for (const [key, value] of Object.entries(params.manual)) {
      form.set(key, value)
    }
  }

  const res = await fetch(`${BASE}/analyze`, { method: 'POST', body: form })
  if (!res.ok) throw new ApiError(await parseErrorDetail(res), res.status)
  return res.json()
}

export async function generateDraft(): Promise<DraftResult> {
  const res = await fetch(`${BASE}/draft`, { method: 'POST' })
  if (!res.ok) throw new ApiError(await parseErrorDetail(res), res.status)
  return res.json()
}

export async function downloadDraftDocx(): Promise<Blob> {
  const res = await fetch(`${BASE}/draft/docx`, { method: 'POST' })
  if (!res.ok) throw new ApiError(await parseErrorDetail(res), res.status)
  return res.blob()
}

export function decisionUrl(docId: string): string {
  return `${BASE}/decision/${encodeURIComponent(docId)}`
}

export function referenceUrl(docId: string): string {
  return `${BASE}/reference/${encodeURIComponent(docId)}`
}
