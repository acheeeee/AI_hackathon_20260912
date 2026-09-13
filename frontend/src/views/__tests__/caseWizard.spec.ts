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
  patchFacts: vi.fn<(params: unknown) => Promise<unknown>>(),
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

const ANALYSIS_FACTS: Record<string, FactFieldValue> = {
  ...FACTS,
  'analysis.keywords': {
    value: '洗錢防制、虛擬資產服務業、登記申請',
    origin: 'llm',
    human_asserted: false,
    reason: 'LLM 依案件內容產生',
    source: { provider: 'fixed' },
    updated_by: 'system',
    updated_at: '2026-09-13T00:00:00Z',
  },
  'disposition.summary': {
    value: '金管會以申請書件及營運準備未完成為由，不予辦理洗錢防制登記。',
    origin: 'llm',
    human_asserted: false,
    reason: 'LLM 摘要行政處分函',
    source: { provider: 'fixed' },
    updated_by: 'system',
    updated_at: '2026-09-13T00:00:00Z',
  },
  'analysis.statute_query': {
    value: '洗錢防制、虛擬資產服務業、登記申請要件、比例原則',
    origin: 'llm',
    human_asserted: false,
    reason: 'LLM 建議法規檢索詞',
    source: { provider: 'fixed' },
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
  it('shows LLM keywords, the disposition summary, and concise suggested statute queries', async () => {
    api.getCase.mockResolvedValue(caseDetail())
    api.getFacts.mockResolvedValue(ANALYSIS_FACTS)
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

    expect(wrapper.text()).toContain('案件相關關鍵字')
    expect(wrapper.text()).toContain('洗錢防制')
    expect(wrapper.text()).toContain('虛擬資產服務業')
    expect(wrapper.text()).toContain('行政處分函摘要')
    expect(wrapper.text()).toContain('金管會以申請書件及營運準備未完成為由')
    expect(wrapper.text()).toContain('建議法規查詢詞')
    expect(wrapper.text()).toContain('登記申請要件')
    expect(wrapper.text()).toContain('固定 Mock 產生')
    expect(wrapper.text()).not.toContain('由 LLM 產生')
  })

  it('lets the reviewer edit and save extraction analysis without changing the document source', async () => {
    api.getCase.mockResolvedValue(caseDetail())
    api.getFacts.mockResolvedValue(ANALYSIS_FACTS)
    api.listDocuments.mockResolvedValue(DOCUMENTS)
    api.getStatuteSelection.mockResolvedValue([])
    api.patchFacts.mockResolvedValue({ case_revision: 4, fields: ANALYSIS_FACTS })

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

    const editButton = wrapper.findAll('button').find((button) => button.text().trim() === '修改')
    expect(editButton).toBeDefined()
    await editButton!.trigger('click')

    const summaryInput = wrapper.get('[aria-label="行政處分函摘要"]')
    await summaryInput.setValue('金管會認定申請人尚未完成人員與監控系統準備，故不予登記。')

    const saveButton = wrapper.findAll('button').find((button) => button.text().trim() === '儲存')
    expect(saveButton).toBeDefined()
    await saveButton!.trigger('click')
    await flushPromises()

    expect(
      api.patchFacts.mock.calls.some(([params]) => {
        const payload = params as Record<string, unknown>
        return (
          payload.caseId === 'case_1' &&
          payload.expectedCaseRevision === 3 &&
          payload.fieldPath === 'disposition.summary' &&
          payload.value ===
            '金管會認定申請人尚未完成人員與監控系統準備，故不予登記。'
        )
      }),
    ).toBe(true)
    expect(api.listDocuments).toHaveBeenCalledWith('case_1')
  })

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
