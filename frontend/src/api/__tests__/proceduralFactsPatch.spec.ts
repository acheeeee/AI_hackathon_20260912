// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'
import { patchFacts } from '@/api/caseapi'

describe('procedural fact edits', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends one versioned PATCH for a clause including explicit cleared values', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          success: true,
          data: { case_revision: 9, fields: {} },
          error: null,
        }),
        { status: 200 },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await patchFacts({
      caseId: 'case_1',
      expectedCaseRevision: 8,
      reason: '核對第1款',
      fieldChanges: [
        { fieldPath: 'appeal.form_defect', value: 'no' },
        { fieldPath: 'appeal.correction_deadline', value: null },
      ],
    })

    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/v1/cases/case_1/facts')
    expect(init?.method).toBe('PATCH')
    expect(JSON.parse(String(init?.body))).toEqual({
      expected_case_revision: 8,
      reason: '核對第1款',
      field_changes: [
        {
          field_path: 'appeal.form_defect',
          value: 'no',
          human_asserted: true,
          reason: '核對第1款',
        },
        {
          field_path: 'appeal.correction_deadline',
          value: null,
          human_asserted: true,
          reason: '核對第1款',
        },
      ],
    })
  })

  it('preserves the existing single-field editor contract', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          success: true,
          data: { case_revision: 3, fields: {} },
          error: null,
        }),
        { status: 200 },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await patchFacts({
      caseId: 'case_1',
      expectedCaseRevision: 2,
      reason: '核對日期',
      fieldPath: 'service.date',
      value: '2026-06-15',
    })

    const [, init] = fetchMock.mock.calls[0]!
    expect(JSON.parse(String(init?.body)).field_changes).toEqual([
      { field_path: 'service.date', value: '2026-06-15', human_asserted: true, reason: '核對日期' },
    ])
  })
})
