// @vitest-environment jsdom

import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getCase: vi.fn(),
  getFacts: vi.fn(),
  listDocuments: vi.fn(),
  getStatuteSelection: vi.fn(),
  startDraftGeneration: vi.fn(),
  getRun: vi.fn(),
  getRunEvents: vi.fn(),
  getProposal: vi.fn(),
}))

vi.mock('@/api/caseapi', () => ({
  ...api,
  CaseApiError: class CaseApiError extends Error {},
  documentContentUrl: vi.fn(() => '/document.pdf'),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { caseId: 'case_1' } }),
  useRouter: () => ({ push: vi.fn() }),
}))

import DraftGenerationPanel from '@/components/DraftGenerationPanel.vue'
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
})
