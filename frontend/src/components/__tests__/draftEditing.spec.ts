// @vitest-environment jsdom

import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getCase: vi.fn<(caseId: string) => Promise<unknown>>(),
  getFacts: vi.fn<(caseId: string) => Promise<unknown>>(),
  listDocuments: vi.fn<(caseId: string) => Promise<unknown>>(),
  getStatuteSelection: vi.fn<(caseId: string) => Promise<unknown>>(),
  startDraftGeneration: vi.fn<(params: unknown) => Promise<unknown>>(),
  getRun: vi.fn<(caseId: string, runId: string) => Promise<unknown>>(),
  getRunEvents: vi.fn<(caseId: string, runId: string) => Promise<unknown>>(),
  getProposal: vi.fn<(caseId: string, proposalId: string) => Promise<unknown>>(),
  createMergePreview: vi.fn<(params: unknown) => Promise<unknown>>(),
  applyProposal: vi.fn<(params: unknown) => Promise<unknown>>(),
  getDraftResource: vi.fn<(caseId: string, draftId: string) => Promise<unknown>>(),
  patchDraftBlock: vi.fn<(params: unknown) => Promise<unknown>>(),
}))

vi.mock('@/api/caseapi', () => ({
  ...api,
  CaseApiError: class CaseApiError extends Error {},
  documentContentUrl: vi.fn<(caseId: string, documentId: string) => string>(
    () => '/document.pdf',
  ),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { caseId: 'case_1' } }),
  useRouter: () => ({ push: vi.fn<(target: unknown) => void>() }),
}))

import DraftGenerationPanel from '@/components/DraftGenerationPanel.vue'
import DraftEditorPanel from '@/components/DraftEditorPanel.vue'
import CaseDetailView from '@/views/CaseDetailView.vue'

describe('draft editing journey', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getFacts.mockResolvedValue({})
    api.getStatuteSelection.mockResolvedValue([
      {
        chunk_id: 'chunk_1',
        document_id: 'doc_1',
        section_id: 'section_1',
        statute_name: '訴願法',
        article_key: '77',
        excerpt: '原文',
      },
    ])
    api.startDraftGeneration.mockResolvedValue({
      run_id: 'run_1',
      state: 'queued',
      draft_id: 'draft_1',
      draft_resource_revision: 'res_1',
      case_revision: 2,
    })
    api.getRun.mockResolvedValue({
      run_id: 'run_1',
      state: 'completed',
      proposal_ids: ['proposal_1'],
    })
    api.getRunEvents.mockResolvedValue([])
    api.getProposal.mockResolvedValue({
      proposal_id: 'proposal_1',
      origin: 'ai',
      run_id: 'run_1',
      mode: 'full',
      state: 'ready',
      change_groups: [
        {
          id: 'group_1',
          change_class: 'structure',
          reason: '生成草稿',
          evidence_ids: [],
          operations: [
            {
              op: 'replace_document',
              after_blocks: [{ block_id: 'reason-1', text: '草稿內容', citations: [] }],
            },
          ],
        },
      ],
    })
    api.createMergePreview.mockResolvedValue({
      preview_id: 'preview_1',
      proposal_id: 'proposal_1',
      current_case_revision: 2,
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
      case_revision: 3,
      resulting_case_revision: 3,
      resource_revisions: { draft_1: 'res_2' },
      invalidated_resources: [],
      unverified_evidence_ids: [],
      proposal_state: 'applied',
    })
    api.getDraftResource.mockResolvedValue({
      resource_id: 'draft_1',
      resource_kind: 'draft',
      resource_revision: 'res_2',
      parent_revision: 'res_1',
      origin: 'merged',
      content: {
        draft_kind: 'appeal_decision',
        title: '訴願決定草稿',
        blocks: [{ block_id: 'reason-1', text: '原始草稿', citations: [] }],
      },
      content_hash: 'content_hash',
      dependencies: {},
      is_head: true,
      freshness: 'current',
      created_by: 'user',
      created_at: '2026-09-13T00:00:00Z',
    })
    api.patchDraftBlock.mockResolvedValue({
      draft_id: 'draft_1',
      resource_revision: 'res_3',
      parent_revision: 'res_2',
      case_revision: 4,
      freshness: 'current',
      blocks: [{ block_id: 'reason-1', text: '人工修改', citations: [] }],
    })
  })

  it('offers to adopt a completed proposal into the official draft head', async () => {
    const wrapper = mount(DraftGenerationPanel, {
      props: { caseId: 'case_1', caseRevision: 1 },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('採用這份草稿')
  })

  it('previews and applies every group before reporting the proposal as adopted', async () => {
    const wrapper = mount(DraftGenerationPanel, {
      props: { caseId: 'case_1', caseRevision: 1 },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()
    await wrapper.get('button').trigger('click')
    await flushPromises()

    const adoptButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('採用這份草稿'))
    expect(adoptButton).toBeDefined()
    await adoptButton!.trigger('click')
    await flushPromises()

    expect(api.createMergePreview).toHaveBeenCalledWith({
      caseId: 'case_1',
      proposalId: 'proposal_1',
      expectedCaseRevision: 2,
      selectedGroupIds: ['group_1'],
    })
    expect(api.applyProposal).toHaveBeenCalledWith({
      caseId: 'case_1',
      proposalId: 'proposal_1',
      expectedCaseRevision: 2,
      previewId: 'preview_1',
      previewHash: 'hash_1',
      acceptedGroupIds: ['group_1'],
    })
    expect(wrapper.emitted('proposal-adopted')).toHaveLength(1)
  })

  it('keeps the current draft untouched when the merge preview reports a conflict', async () => {
    api.createMergePreview.mockResolvedValue({
      preview_id: 'preview_conflict',
      proposal_id: 'proposal_1',
      current_case_revision: 3,
      selected_group_ids: ['group_1'],
      preview_hash: 'hash_conflict',
      conflicts: [{ code: 'SAME_DOCUMENT_CHANGED' }],
      missing_group_dependencies: [],
      unverified_evidence_ids: [],
      diffs: [],
      can_apply: false,
    })
    const wrapper = mount(DraftGenerationPanel, {
      props: { caseId: 'case_1', caseRevision: 3 },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()
    await wrapper.get('button').trigger('click')
    await flushPromises()
    const adoptButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('採用這份草稿'))
    await adoptButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('這一版不會自動解決衝突')
    expect(api.applyProposal).not.toHaveBeenCalled()
  })

  it('mounts a draft editor when the case has a draft head', async () => {
    api.getCase.mockResolvedValue({
      case_id: 'case_1',
      title: '測試案件',
      official_case_no: null,
      workflow_state: 'drafting',
      processing_status: 'processing',
      case_revision: 3,
      created_at: '2026-09-13T00:00:00Z',
      updated_at: '2026-09-13T00:00:00Z',
      active_heads: {
        draft_1: { revision_id: 'res_2', kind: 'draft', freshness: 'current' },
      },
    })
    api.listDocuments.mockResolvedValue([])

    const wrapper = shallowMount(CaseDetailView)
    await flushPromises()

    expect(wrapper.find('draft-editor-panel-stub').exists()).toBe(true)
  })

  it('saves one edited block against the displayed resource revision', async () => {
    const wrapper = mount(DraftEditorPanel, {
      props: {
        caseId: 'case_1',
        caseRevision: 3,
        draftId: 'draft_1',
        draftHead: { revision_id: 'res_2', kind: 'draft', freshness: 'current' },
      },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    await wrapper.get('textarea').setValue('人工修改')
    const saveButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('儲存此段'))
    await saveButton!.trigger('click')
    await flushPromises()

    expect(api.patchDraftBlock).toHaveBeenCalledWith({
      caseId: 'case_1',
      draftId: 'draft_1',
      expectedCaseRevision: 3,
      baseResourceRevision: 'res_2',
      block: { block_id: 'reason-1', text: '人工修改', citations: [] },
    })
    expect(wrapper.emitted('draft-updated')).toHaveLength(1)
  })

  it('labels a program-created placeholder as a system shell instead of a merged version', async () => {
    api.getDraftResource.mockResolvedValue({
      resource_id: 'draft_1',
      resource_kind: 'draft',
      resource_revision: 'res_1',
      parent_revision: null,
      origin: 'program',
      content: {
        draft_kind: 'appeal_decision',
        title: '訴願決定草稿',
        blocks: [{ block_id: 'placeholder', text: '（尚未生成內容）', citations: [] }],
      },
      content_hash: 'content_hash',
      dependencies: {},
      is_head: true,
      freshness: 'stale',
      created_by: 'system',
      created_at: '2026-09-13T00:00:00Z',
    })
    const wrapper = mount(DraftEditorPanel, {
      props: {
        caseId: 'case_1',
        caseRevision: 2,
        draftId: 'draft_1',
        draftHead: { revision_id: 'res_1', kind: 'draft', freshness: 'stale' },
      },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('系統空殼')
    expect(wrapper.text()).not.toContain('合併版本')
  })
})
