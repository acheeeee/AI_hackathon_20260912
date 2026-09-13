// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'

import { intakeCase } from '@/api/caseapi'

describe('intakeCase on an HTTP IP origin', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('uses getRandomValues when randomUUID is unavailable and still sends the upload', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          success: true,
          data: { case_id: 'case_1', case_revision: 1, extracted_fields: {} },
          error: null,
        }),
        { status: 201, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('crypto', {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.forEach((_, index) => {
          bytes[index] = index
        })
        return bytes
      },
    })

    await intakeCase({
      appealPdf: new File(['synthetic'], 'appeal.pdf', { type: 'application/pdf' }),
    })

    expect(fetchMock).toHaveBeenCalledOnce()
    const [, init] = fetchMock.mock.calls[0]!
    expect(init?.headers).toEqual({
      'Idempotency-Key': '00010203-0405-4607-8809-0a0b0c0d0e0f',
    })
    const form = init?.body as FormData
    expect(form.has('consent_to_online_analysis')).toBe(false)
  })

  it('sends online-analysis consent only when it is explicitly enabled', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          success: true,
          data: {
            case_id: 'case_1',
            case_revision: 1,
            extracted_fields: {},
            analysis_status: 'online_completed',
            analysis_error: null,
          },
          error: null,
        }),
        { status: 201, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('crypto', {
      randomUUID: () => 'consent-key',
      getRandomValues: (bytes: Uint8Array) => bytes,
    })

    await intakeCase({
      appealPdf: new File(['synthetic'], 'appeal.pdf', { type: 'application/pdf' }),
      consentToOnlineAnalysis: true,
    })

    const [, init] = fetchMock.mock.calls[0]!
    const form = init?.body as FormData
    expect(form.get('consent_to_online_analysis')).toBe('true')
  })
})
