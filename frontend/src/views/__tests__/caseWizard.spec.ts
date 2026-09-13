// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import type { CaseDetail, FactFieldValue, CaseDocument, SelectedStatute } from '@/api/caseapi'

const api = vi.hoisted(() => ({
  getCase: vi.fn<(caseId: string) => Promise<unknown>>(),
  getFacts: vi.fn<(caseId: string) => Promise<unknown>>(),
  listDocuments: vi.fn<(caseId: string) => Promise<unknown>>(),
  getStatuteSelection: vi.fn<(caseId: string) => Promise<unknown>>(),
}))

vi.mock('@/api/caseapi', async () => {
  const actual = await vi.importActual<typeof import('@/api/caseapi')>('@/api/caseapi')
  return {
    ...actual,
    ...api,
    documentContentUrl: vi.fn<(caseId: string, documentId: string) => string>(() => '/document.pdf'),
  }
})

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { caseId: 'case_1' } }),
  useRouter: () => ({ push: vi.fn<(target: unknown) => void>() }),
}))

import CaseDetailView from '@/views/CaseDetailView.vue'

function caseDetail(overrides: Partial<CaseDetail> = {}): CaseDetail {
  return {
    case_id: 'case_1',
    title: '案01',
    official_case_no: null,
    workflow_state: 'human_review',
    processing_status: 'processing',
    case_revision: 3,
    created_at: '2026-09-13T00:00:00Z',
    updated_at: '2026-09-13T00:00:00Z',
    active_heads: {},
    ...overrides,
  }
}

const FACTS: Record<string, FactFieldValue> = {
  'appellant.name': {
    value: '絕○○○股份有限公司',
    origin: 'program',
    human_asserted: false,
    reason: '',
    source: null,
    updated_by: 'system',
    updated_at: '2026-09-13T00:00:00Z',
  },
}

const DOCUMENTS: CaseDocument[] = [
  {
    document_id: 'doc_1',
    document_role: 'appeal',
    source_filename: 'appeal.pdf',
    source_sha256: 'hash',
    page_count: 3,
    created_at: '2026-09-13T00:00:00Z',
  },
]

// `wrapper.isVisible()` walks every ancestor via jsdom's `getComputedStyle`,
// which has proven unreliable here once several sibling `v-show` targets
// flip their inline `display` back and forth (readings for two different
// elements come back swapped). Vue's own inline `style` attribute for
// `v-show` is unambiguous, so read that directly instead.
function visibleStepIndex(wrapper: ReturnType<typeof mount>): number[] {
  return wrapper
    .findAll('.step-panel')
    .map((panel, index) => ((panel.attributes('style') ?? '').includes('display: none') ? -1 : index))
    .filter((index) => index !== -1)
}

describe('case detail wizard shell', () => {
  it('starts on the first not-yet-completed step and shows only that step', async () => {
    api.getCase.mockResolvedValue(caseDetail())
    api.getFacts.mockResolvedValue(FACTS)
    api.listDocuments.mockResolvedValue(DOCUMENTS)
    api.getStatuteSelection.mockResolvedValue([])

    const wrapper = mount(CaseDetailView, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          ProceduralReviewPanel: true,
          StatuteSelectionPanel: true,
          DraftGenerationPanel: true,
          DraftEditorPanel: true,
          ChatSidebar: true,
        },
      },
    })
    await flushPromises()

    // step 0 (upload) is already satisfied because the case has documents;
    // step 1 (extract) has no confirmation yet, so the wizard should land there.
    expect(visibleStepIndex(wrapper)).toEqual([1])
  })

  it('does not let a click jump past a step that has not been unlocked yet', async () => {
    api.getCase.mockResolvedValue(caseDetail())
    api.getFacts.mockResolvedValue(FACTS)
    api.listDocuments.mockResolvedValue(DOCUMENTS)
    api.getStatuteSelection.mockResolvedValue([])

    const wrapper = mount(CaseDetailView, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          ProceduralReviewPanel: true,
          StatuteSelectionPanel: true,
          DraftGenerationPanel: true,
          DraftEditorPanel: true,
          ChatSidebar: true,
        },
      },
    })
    await flushPromises()

    const steps = wrapper.findAll('.wizard-step')
    await steps[3]!.trigger('click')
    await flushPromises()

    expect(visibleStepIndex(wrapper)).toEqual([1])
  })

  it('advances one step at a time through 下一步 and back through 上一步', async () => {
    api.getCase.mockResolvedValue(caseDetail())
    api.getFacts.mockResolvedValue(FACTS)
    api.listDocuments.mockResolvedValue(DOCUMENTS)
    api.getStatuteSelection.mockResolvedValue([])

    const wrapper = mount(CaseDetailView, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          ProceduralReviewPanel: true,
          StatuteSelectionPanel: true,
          DraftGenerationPanel: true,
          DraftEditorPanel: true,
          ChatSidebar: true,
        },
      },
    })
    await flushPromises()

    await wrapper.get('.wizard-next').trigger('click')
    await flushPromises()
    expect(visibleStepIndex(wrapper)).toEqual([2])

    await wrapper.get('.wizard-prev').trigger('click')
    await flushPromises()
    expect(visibleStepIndex(wrapper)).toEqual([1])
  })

  it('keeps 下一步 disabled on the statute step until a selection has actually been saved', async () => {
    api.getCase.mockResolvedValue(caseDetail())
    api.getFacts.mockResolvedValue(FACTS)
    api.listDocuments.mockResolvedValue(DOCUMENTS)
    api.getStatuteSelection.mockResolvedValue([])

    const wrapper = mount(CaseDetailView, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          ProceduralReviewPanel: true,
          StatuteSelectionPanel: true,
          DraftGenerationPanel: true,
          DraftEditorPanel: true,
          ChatSidebar: true,
        },
      },
    })
    await flushPromises()
    await wrapper.get('.wizard-next').trigger('click')
    await wrapper.get('.wizard-next').trigger('click')
    await flushPromises()
    expect(visibleStepIndex(wrapper)).toEqual([3])

    expect((wrapper.get('.wizard-next').element as HTMLButtonElement).disabled).toBe(true)
  })

  it('resumes at the furthest real step on reload once statutes are already saved', async () => {
    const selected: SelectedStatute[] = [
      {
        chunk_id: 'chunk_1',
        document_id: 'doc_1',
        section_id: 'sec_1',
        statute_name: '洗錢防制法',
        article_key: '6',
        excerpt: '第 6 條…',
      },
    ]
    api.getCase.mockResolvedValue(caseDetail())
    api.getFacts.mockResolvedValue(FACTS)
    api.listDocuments.mockResolvedValue(DOCUMENTS)
    api.getStatuteSelection.mockResolvedValue(selected)

    const wrapper = mount(CaseDetailView, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          ProceduralReviewPanel: true,
          StatuteSelectionPanel: true,
          DraftGenerationPanel: true,
          DraftEditorPanel: true,
          ChatSidebar: true,
        },
      },
    })
    await flushPromises()

    expect(visibleStepIndex(wrapper)).toEqual([4])
  })
})
