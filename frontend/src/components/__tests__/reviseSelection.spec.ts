// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { waitForCondition } from './testUtils'
import type { DraftBlockTarget, ProposalDetail } from '@/api/caseapi'

// jsdom 沒有實作 Element.scrollTo；ChatSidebar 開啟時會呼叫它捲到底部，
// 這裡補一個 no-op，跟元件邏輯無關，純粹補齊測試環境缺的瀏覽器 API。
Element.prototype.scrollTo = Element.prototype.scrollTo ?? (() => {})

const api = vi.hoisted(() => ({
  createThread: vi.fn<(caseId: string) => Promise<string>>(),
  sendMessage: vi.fn<(params: unknown) => Promise<unknown>>(),
  getRun: vi.fn<(caseId: string, runId: string) => Promise<unknown>>(),
  getRunEvents: vi.fn<(caseId: string, runId: string) => Promise<unknown>>(),
  listMessages: vi.fn<(caseId: string, threadId: string) => Promise<unknown>>(),
  getProposal: vi.fn<(caseId: string, proposalId: string) => Promise<unknown>>(),
  createMergePreview: vi.fn<(params: unknown) => Promise<unknown>>(),
  applyProposal: vi.fn<(params: unknown) => Promise<unknown>>(),
  rejectProposal: vi.fn<(params: unknown) => Promise<unknown>>(),
  getDraftResource: vi.fn<(caseId: string, draftId: string) => Promise<unknown>>(),
  patchDraftBlock: vi.fn<(params: unknown) => Promise<unknown>>(),
}))

vi.mock('@/api/caseapi', async () => {
  const actual = await vi.importActual<typeof import('@/api/caseapi')>('@/api/caseapi')
  return { ...actual, ...api }
})

import ChatSidebar from '@/components/ChatSidebar.vue'
import DraftEditorPanel from '@/components/DraftEditorPanel.vue'

const BLOCK_TEXT = '原處分機關認事用法並無違誤，故本件無理由。'
const SELECTED = '原處分機關認事用法並無違誤'

function target(): DraftBlockTarget {
  return {
    kind: 'draft_block',
    resource_id: 'draft_1',
    resource_revision: 'res_1',
    block_id: 'reason-1',
    char_start: 0,
    char_end: SELECTED.length,
    selected_text: SELECTED,
    selected_text_sha256: 'x'.repeat(64),
  }
}

function proposal(afterValue: string): ProposalDetail {
  return {
    proposal_id: 'proposal_1',
    origin: 'ai',
    run_id: 'run_1',
    mode: 'local',
    state: 'ready',
    base_case_revision: 3,
    applied_group_ids: [],
    change_groups: [
      {
        id: 'group_1',
        change_class: 'wording',
        reason: '依使用者選取範圍與修改指示產生的局部文字候選',
        evidence_ids: [],
        operations: [{ op: 'replace_text', after_value: afterValue }],
      },
    ],
  }
}

function mockCompletedRun() {
  api.createThread.mockResolvedValue('thread_1')
  api.sendMessage.mockResolvedValue({
    message_id: 'msg_1',
    run_id: 'run_1',
    state: 'queued',
    case_revision: 3,
  })
  api.getRun.mockResolvedValue({
    run_id: 'run_1',
    state: 'completed',
    proposal_ids: ['proposal_1'],
  })
  api.getRunEvents.mockResolvedValue([])
  api.listMessages.mockResolvedValue([
    {
      message_id: 'msg_2',
      role: 'assistant',
      content: 'AI 已依指示改寫選取範圍，內容尚未經法律覆核，請人工確認後再採用。',
      intent: null,
      target: null,
      run_id: 'run_1',
    },
  ])
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('DraftEditorPanel revise-selection entry point', () => {
  it('emits revise-selection with the exact selected range when the button is clicked', async () => {
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
    textarea.focus()
    textarea.setSelectionRange(0, SELECTED.length)
    textarea.dispatchEvent(new Event('select', { bubbles: true }))
    await flushPromises()

    await wrapper.get('button.revise-selection').trigger('click')
    await waitForCondition(() => Boolean(wrapper.emitted('revise-selection')))

    const emitted = wrapper.emitted('revise-selection')
    expect(emitted).toBeTruthy()
    const [, emittedTarget] = emitted![0] as [string, DraftBlockTarget]
    expect(emittedTarget.selected_text).toBe(SELECTED)
    expect(emittedTarget.char_start).toBe(0)
  })
})

describe('ChatSidebar local revision flow', () => {
  it('sends revise_selection with the attached target once the user submits an instruction', async () => {
    mockCompletedRun()
    api.getProposal.mockResolvedValue(proposal('原處分機關之認事用法，核無違誤之處。'))

    const wrapper = mount(ChatSidebar, {
      props: { caseId: 'case_1', caseRevision: 3 },
      global: { plugins: [ElementPlus] },
    })
    ;(wrapper.vm as unknown as { attachSelectionForRevision: (l: string, t: DraftBlockTarget) => void })
      .attachSelectionForRevision(SELECTED, target())
    await flushPromises()

    expect(wrapper.text()).toContain('正在修改')

    await wrapper.get('input').setValue('改得更正式一點')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(api.sendMessage).toHaveBeenCalledWith(
      expect.objectContaining({ intent: 'revise_selection', target: target(), content: '改得更正式一點' }),
    )
    expect(wrapper.text()).not.toContain('正在修改')
  })

  it('shows a before/after diff and adopts the candidate through the existing merge preview + apply flow', async () => {
    mockCompletedRun()
    api.getProposal.mockResolvedValue(proposal('原處分機關之認事用法，核無違誤之處。'))
    api.createMergePreview.mockResolvedValue({
      preview_id: 'preview_1',
      proposal_id: 'proposal_1',
      current_case_revision: 3,
      selected_group_ids: ['group_1'],
      preview_hash: 'hash_1',
      conflicts: [],
      missing_group_dependencies: [],
      unverified_evidence_ids: [],
      diffs: [],
      can_apply: true,
    })
    api.applyProposal.mockResolvedValue({
      applied_group_ids: ['group_1'],
      case_revision: 4,
      resulting_case_revision: 4,
      resource_revisions: { draft_1: 'res_2' },
      invalidated_resources: [],
      unverified_evidence_ids: [],
      proposal_state: 'applied',
    })

    const wrapper = mount(ChatSidebar, {
      props: { caseId: 'case_1', caseRevision: 3 },
      global: { plugins: [ElementPlus] },
    })
    ;(wrapper.vm as unknown as { attachSelectionForRevision: (l: string, t: DraftBlockTarget) => void })
      .attachSelectionForRevision(SELECTED, target())
    await wrapper.get('input').setValue('改得更正式一點')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain(SELECTED)
    expect(wrapper.text()).toContain('原處分機關之認事用法，核無違誤之處。')

    await wrapper.get('button.accept-revision').trigger('click')
    await flushPromises()

    expect(api.createMergePreview).toHaveBeenCalledWith({
      caseId: 'case_1',
      proposalId: 'proposal_1',
      expectedCaseRevision: 3,
      selectedGroupIds: ['group_1'],
    })
    expect(api.applyProposal).toHaveBeenCalledWith({
      caseId: 'case_1',
      proposalId: 'proposal_1',
      expectedCaseRevision: 3,
      previewId: 'preview_1',
      previewHash: 'hash_1',
      acceptedGroupIds: ['group_1'],
    })
    expect(wrapper.emitted('draft-updated')).toHaveLength(1)
  })

  it('rejects the candidate without ever calling the merge/apply endpoints', async () => {
    mockCompletedRun()
    api.getProposal.mockResolvedValue(proposal('原處分機關之認事用法，核無違誤之處。'))
    api.rejectProposal.mockResolvedValue(proposal('原處分機關之認事用法，核無違誤之處。'))

    const wrapper = mount(ChatSidebar, {
      props: { caseId: 'case_1', caseRevision: 3 },
      global: { plugins: [ElementPlus] },
    })
    ;(wrapper.vm as unknown as { attachSelectionForRevision: (l: string, t: DraftBlockTarget) => void })
      .attachSelectionForRevision(SELECTED, target())
    await wrapper.get('input').setValue('改得更正式一點')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    await wrapper.get('button.reject-revision').trigger('click')
    await flushPromises()

    expect(api.rejectProposal).toHaveBeenCalledWith(
      expect.objectContaining({ caseId: 'case_1', proposalId: 'proposal_1' }),
    )
    expect(api.createMergePreview).not.toHaveBeenCalled()
    expect(api.applyProposal).not.toHaveBeenCalled()
    expect(wrapper.find('button.accept-revision').exists()).toBe(false)
    expect(wrapper.find('button.reject-revision').exists()).toBe(false)
  })

  it('keeps the draft untouched and shows a conflict message when the merge preview cannot be applied', async () => {
    mockCompletedRun()
    api.getProposal.mockResolvedValue(proposal('原處分機關之認事用法，核無違誤之處。'))
    api.createMergePreview.mockResolvedValue({
      preview_id: 'preview_1',
      proposal_id: 'proposal_1',
      current_case_revision: 3,
      selected_group_ids: ['group_1'],
      preview_hash: 'hash_1',
      conflicts: [{ code: 'SAME_DOCUMENT_CHANGED' }],
      missing_group_dependencies: [],
      unverified_evidence_ids: [],
      diffs: [],
      can_apply: false,
    })

    const wrapper = mount(ChatSidebar, {
      props: { caseId: 'case_1', caseRevision: 3 },
      global: { plugins: [ElementPlus] },
    })
    ;(wrapper.vm as unknown as { attachSelectionForRevision: (l: string, t: DraftBlockTarget) => void })
      .attachSelectionForRevision(SELECTED, target())
    await wrapper.get('input').setValue('改得更正式一點')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    await wrapper.get('button.accept-revision').trigger('click')
    await flushPromises()

    expect(api.applyProposal).not.toHaveBeenCalled()
    expect(wrapper.emitted('draft-updated')).toBeFalsy()
    expect(wrapper.find('button.accept-revision').exists()).toBe(true)
  })
})
