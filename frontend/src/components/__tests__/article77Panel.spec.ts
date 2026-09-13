// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import type { ProceduralReview } from '@/api/caseapi'

const api = vi.hoisted(() => ({
  getProceduralReview: vi.fn<(caseId: string) => Promise<unknown>>(),
  patchFacts: vi.fn<(params: unknown) => Promise<unknown>>(),
}))

vi.mock('@/api/caseapi', async () => {
  const actual = await vi.importActual<typeof import('@/api/caseapi')>('@/api/caseapi')
  return { ...actual, ...api }
})

import ProceduralReviewPanel from '@/components/ProceduralReviewPanel.vue'
import { ARTICLE_77_CLAUSES } from '@/utils/article77'

function review(overrides: Partial<ProceduralReview> = {}): ProceduralReview {
  return {
    case_id: 'case_1',
    status: 'overdue',
    deadline_date: '2025-06-05',
    days_from_deadline: 92,
    missing_fields: [],
    statute_basis: '訴願法第14條第1項：訴願之提起，應自行政處分達到或公告期滿之次日起三十日內為之。',
    caveats: ['未考慮國定假日順延（行政程序法第48條第4項），僅算日曆天數。'],
    legal_review_status: 'not_reviewed',
    ...overrides,
  }
}

describe('ProceduralReviewPanel: full article 77 disclosure', () => {
  it('lists all eight clauses with a stated reason each, not just clause 2', async () => {
    api.getProceduralReview.mockResolvedValue(review())

    const wrapper = mount(ProceduralReviewPanel, {
      props: { caseId: 'case_1', caseRevision: 3 },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    for (const clause of ARTICLE_77_CLAUSES) {
      expect(wrapper.text()).toContain(clause.title)
    }
    expect(wrapper.text()).toContain('尚無自動判定規則')
    expect(wrapper.text()).toContain('待人工確認')
  })

  it('never asserts a final inadmissibility decision even when clause 2 is overdue', async () => {
    // 條文本身的引述（例如頁首說明段落引用第 77 條「應為不受理之決定」的
    // 文字）沒問題——那是在解釋法條，不是系統在斷言本案的結論。真正不能
    // 出現的是把「本案」與「不受理」直接綁在一起的斷言句。
    api.getProceduralReview.mockResolvedValue(review({ status: 'overdue' }))

    const wrapper = mount(ProceduralReviewPanel, {
      props: { caseId: 'case_1', caseRevision: 3 },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    expect(wrapper.text()).not.toContain('本件訴願不受理')
    expect(wrapper.text()).not.toContain('本案應為不受理')
    expect(wrapper.text()).not.toContain('決定：不受理')
    expect(wrapper.text()).toContain('系統不做決定')
    expect(wrapper.text()).toContain('系統不做最終判斷')
  })

  it('does not claim the other clauses are inapplicable or already checked against a case archive', async () => {
    api.getProceduralReview.mockResolvedValue(review({ status: 'within_period', days_from_deadline: -5 }))

    const wrapper = mount(ProceduralReviewPanel, {
      props: { caseId: 'case_1', caseRevision: 3 },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    expect(wrapper.text()).not.toContain('不適用')
    expect(wrapper.text()).not.toContain('查無前案')
  })
})
