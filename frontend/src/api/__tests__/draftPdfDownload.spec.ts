// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CaseApiError, downloadDraftPdf } from '@/api/caseapi'

describe('downloadDraftPdf', () => {
  const fetchMock = vi.fn<typeof fetch>()
  const createObjectUrl = vi.fn<(blob: Blob) => string>(() => 'blob:draft-pdf')
  const revokeObjectUrl = vi.fn<(url: string) => void>()
  let clickedDownload = ''

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('URL', {
      createObjectURL: createObjectUrl,
      revokeObjectURL: revokeObjectUrl,
    })
    clickedDownload = ''
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clickedDownload = this.download
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('requests the draft PDF and triggers a browser download using the safe filename', async () => {
    const pdf = new Blob(['%PDF-1.7'], { type: 'application/pdf' })
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: new Headers({
        'Content-Type': 'application/pdf',
        'Content-Disposition': 'attachment; filename="appeal-decision-draft.pdf"',
      }),
      blob: vi.fn<() => Promise<Blob>>().mockResolvedValue(pdf),
    } as unknown as Response)

    await downloadDraftPdf({ caseId: 'case A', draftId: 'draft/1' })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/cases/case%20A/drafts/draft%2F1/pdf',
      { headers: { Accept: 'application/pdf' } },
    )
    expect(createObjectUrl).toHaveBeenCalledWith(pdf)
    expect(clickedDownload).toBe('appeal-decision-draft.pdf')
    expect(revokeObjectUrl).toHaveBeenCalledWith('blob:draft-pdf')
  })

  it('converts an API envelope failure into a CaseApiError', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      headers: new Headers({ 'Content-Type': 'application/json' }),
      json: vi.fn<() => Promise<unknown>>().mockResolvedValue({
        success: false,
        data: null,
        error: {
          code: 'RESOURCE_NOT_FOUND',
          message: '找不到資源，或沒有讀取權限',
          details: {},
          retryable: false,
        },
      }),
    } as unknown as Response)

    const error: unknown = await downloadDraftPdf({
      caseId: 'case_1',
      draftId: 'draft_1',
    }).catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(CaseApiError)
    expect(error).toMatchObject({
      code: 'RESOURCE_NOT_FOUND',
      status: 404,
    })
  })
})
