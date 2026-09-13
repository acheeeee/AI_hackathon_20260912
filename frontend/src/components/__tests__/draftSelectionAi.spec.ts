// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import { sha256Hex } from '@/utils/draftSelection'
import { waitForCondition } from './testUtils'

const api = vi.hoisted(() => ({
  getDraftResource: vi.fn<(caseId: string, draftId: string) => Promise<unknown>>(),
  patchDraftBlock: vi.fn<(params: unknown) => Promise<unknown>>(),
}))

vi.mock('@/api/caseapi', async () => {
  const actual = await vi.importActual<typeof import('@/api/caseapi')>('@/api/caseapi')
  return { ...actual, getDraftResource: api.getDraftResource, patchDraftBlock: api.patchDraftBlock }
})

import DraftEditorPanel from '@/components/DraftEditorPanel.vue'

const PHRASE = '原處分機關認事用法並無違誤'
const BLOCK_TEXT = `${PHRASE}。${PHRASE}，故本件無理由。`

function selectSecondOccurrence(textarea: HTMLTextAreaElement) {
  const start = BLOCK_TEXT.indexOf(PHRASE, BLOCK_TEXT.indexOf(PHRASE) + 1)
  const end = start + PHRASE.length
  textarea.focus()
  textarea.setSelectionRange(start, end)
  textarea.dispatchEvent(new Event('select', { bubbles: true }))
  return { start, end }
}

describe('draft selection AI entry point', () => {
  it('mounts a draft editor whose block currently offers no way to ask AI about a selection', async () => {
    api.getDraftResource.mockResolvedValue({
      resource_id: 'draft_1',
      resource_kind: 'draft',
      resource_revision: 'res_1',
      parent_revision: null,
      origin: 'human',
      content: {
        draft_kind: 'decision',
        title: '訴願決定書草稿',
        blocks: [{ block_id: 'reason-1', text: BLOCK_TEXT, citations: [] }],
      },
      content_hash: 'hash',
      dependencies: {},
      is_head: true,
      freshness: 'current',
      created_by: 'user',
      created_at: '2026-09-13T00:00:00Z',
    })

    const wrapper = mount(DraftEditorPanel, {
      props: {
        caseId: 'case_1',
        caseRevision: 3,
        draftId: 'draft_1',
        draftHead: { revision_id: 'res_1', kind: 'draft', freshness: 'current' },
      },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    const textarea = wrapper.get('textarea').element as HTMLTextAreaElement
    selectSecondOccurrence(textarea)
    await flushPromises()

    expect(wrapper.text()).toContain('請 AI 解釋')

    await wrapper.get('button.explain-selection').trigger('click')
    await waitForCondition(() => Boolean(wrapper.emitted('explain-selection')))

    const emitted = wrapper.emitted('explain-selection')
    expect(emitted).toBeTruthy()
    const [, target] = emitted![0] as [string, Record<string, unknown>]
    expect(target.kind).toBe('draft_block')
    expect(target.block_id).toBe('reason-1')
    expect(target.selected_text).toBe(PHRASE)
    expect(target.char_start).not.toBe(0)
    expect(target.selected_text_sha256).toBe(await sha256Hex(PHRASE))
  })
})
