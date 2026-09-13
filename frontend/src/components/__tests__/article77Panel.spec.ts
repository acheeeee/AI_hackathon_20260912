// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
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
  beforeEach(() => vi.clearAllMocks())
  it('shows the complete second-clause text, including the Article 57 written-appeal branch', () => {
    expect(ARTICLE_77_CLAUSES[1]?.title).toContain('未於第 57 條但書所定期間內補送訴願書')
  })

  it('shows an automatic rule, outcome, and case-specific reason for every clause', async () => {
    const clauseAssessments = ARTICLE_77_CLAUSES.map((clause) => {
      const needsLegalJudgment = clause.no === 3 || clause.no === 8
      return {
        clause_no: clause.no,
        rule_id: `art77_para${clause.no}`,
        input: { case_id: 'case_1' },
        status:
          clause.no === 2
            ? 'TRIGGERED'
            : needsLegalJudgment
              ? 'NEEDS_HUMAN'
              : 'INSUFFICIENT_EVIDENCE',
        rule_description:
          clause.no === 2
            ? '比較行政處分送達日、法定期間與訴願收件日。'
            : needsLegalJudgment
              ? `第 ${clause.no} 款涉及實質法律判斷，規則固定轉交人工覆核。`
              : `第 ${clause.no} 款 mock：依已擷取欄位提出初步訊號，再交由承辦人覆核。`,
        reason:
          clause.no === 2
            ? '收件日晚於試算期限 92 天，規則標記為可能逾期。'
            : `第 ${clause.no} 款目前缺少足以自動排除的資料，需人工覆核。`,
        evaluation_mode:
          clause.no === 2 ? 'rule' : needsLegalJudgment ? 'manual_review' : 'mock',
      }
    })
    api.getProceduralReview.mockResolvedValue({
      ...review(),
      clause_assessments: clauseAssessments,
    })

    const wrapper = mount(ProceduralReviewPanel, {
      props: { caseId: 'case_1', caseRevision: 3 },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    for (const [index, clause] of ARTICLE_77_CLAUSES.entries()) {
      const assessment = clauseAssessments[index]!
      const productText = (text: string) =>
        text.replace(/Mock 規則/gi, '初步檢核').replace(/mock/gi, '初步檢核')
      expect(wrapper.text()).toContain(clause.title)
      expect(wrapper.text()).toContain(productText(assessment.rule_description))
      expect(wrapper.text()).toContain(productText(assessment.reason))
    }
    expect(wrapper.findAll('.clause-row')).toHaveLength(8)
    expect(wrapper.text()).toContain('可能成立')
    expect(wrapper.text()).toContain('需人工覆核')
    expect(wrapper.text()).toContain('初步檢核')
    expect(wrapper.text()).not.toContain('Mock')
    expect(wrapper.text()).not.toContain('尚無自動判定規則')
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

function editableReview(revision = 7, defect: string | null = null) {
  return review({
    status: 'within_period',
    days_from_deadline: -5,
    ...{
      case_revision: revision,
      field_definitions: [
        {
          field_path: 'appeal.form_defect', label: '訴願書程式欠缺', input_type: 'select',
          options: [{ value: 'yes', label: '有欠缺' }, { value: 'no', label: '無欠缺' }],
        },
        {
          field_path: 'appeal.correction_deadline', label: '訴願補正期限',
          input_type: 'date', options: [],
        },
        {
          field_path: 'appellant.entity_type', label: '訴願人類型', input_type: 'select',
          options: [{ value: 'legal_person', label: '法人' }, { value: 'individual', label: '自然人' }],
        },
      ],
    },
    clause_assessments: [
      {
        clause_no: 1, rule_id: 'art77_para1', evaluation_mode: 'rule',
        input: { 'appeal.form_defect': defect, 'appeal.correction_deadline': '2026-07-10' },
        status: defect === 'no' ? 'NOT_TRIGGERED' : 'INSUFFICIENT_EVIDENCE',
        rule_description: '核對程式欠缺及補正情形。',
        reason: defect === 'no' ? '目前資料未發現程式欠缺。' : '尚未確認程式欠缺。',
        ...{
          missing_fields: defect ? [] : ['appeal.form_defect'],
          input_sources: {
            'appeal.correction_deadline': {
              origin: 'program', reason: '從通知擷取',
              source: { document_role: 'appeal', excerpt: '請於115年7月10日前補正訴願書。' },
            },
          },
        },
      },
      {
        clause_no: 5, rule_id: 'art77_para5', evaluation_mode: 'rule',
        input: { 'appellant.entity_type': 'legal_person' },
        status: 'INSUFFICIENT_EVIDENCE', rule_description: '核對代表人。', reason: '請補代表人。',
        ...{ missing_fields: [], input_sources: {} },
      },
    ],
  })
}

async function mountEditable() {
  api.getProceduralReview.mockResolvedValue(editableReview())
  const wrapper = mount(ProceduralReviewPanel, {
    props: { caseId: 'case_1', caseRevision: 3 },
    global: { plugins: [ElementPlus] },
  })
  await flushPromises()
  return wrapper
}

describe('ProceduralReviewPanel: actionable procedural evidence', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows missing field labels, extracted provenance and editable populated fields without defaulting yes/no', async () => {
    const wrapper = await mountEditable()

    expect(wrapper.text()).toContain('尚缺：訴願書程式欠缺')
    expect(wrapper.text()).toContain('文件擷取')
    expect(wrapper.text()).toContain('請於115年7月10日前補正訴願書。')
    expect(wrapper.findAll('details.clause-editor')).toHaveLength(2)
    expect((wrapper.get('[name="appeal.form_defect"]').element as HTMLSelectElement).value).toBe('')
    expect((wrapper.get('[name="appellant.entity_type"]').element as HTMLSelectElement).value).toBe('legal_person')
  })

  it('saves changed fields atomically with the review revision, supports clearing and refreshes outcomes', async () => {
    const wrapper = await mountEditable()
    await wrapper.get('[name="appeal.form_defect"]').setValue('no')
    await wrapper.get('[name="appeal.correction_deadline"]').setValue('')
    api.patchFacts.mockResolvedValue({ case_revision: 8, fields: {} })
    api.getProceduralReview.mockResolvedValue(editableReview(8, 'no'))

    await wrapper.get('[data-clause="1"] .save-clause').trigger('click')
    await flushPromises()

    expect(api.patchFacts).toHaveBeenCalledTimes(1)
    expect(api.patchFacts).toHaveBeenCalledWith(expect.objectContaining({
      caseId: 'case_1', expectedCaseRevision: 7,
      fieldChanges: [
        { fieldPath: 'appeal.form_defect', value: 'no' },
        { fieldPath: 'appeal.correction_deadline', value: null },
      ],
    }))
    expect(wrapper.emitted('facts-updated')).toHaveLength(1)
    expect(wrapper.get('[data-clause="1"]').text()).toContain('目前資料未發現程式欠缺。')
    expect(wrapper.get('[data-clause="1"]').text()).toContain('未觸發')
  })

  it('refreshes for a parent revision change while retaining unsaved changes in a different field', async () => {
    const wrapper = await mountEditable()
    await wrapper.get('[name="appeal.form_defect"]').setValue('no')
    api.getProceduralReview.mockResolvedValue(editableReview(8))
    await wrapper.setProps({ caseRevision: 8 })
    await flushPromises()

    expect(api.getProceduralReview).toHaveBeenCalledTimes(2)
    expect((wrapper.get('[name="appeal.form_defect"]').element as HTMLSelectElement).value).toBe('no')
    api.patchFacts.mockResolvedValue({ case_revision: 9, fields: {} })
    await wrapper.get('[data-clause="1"] .save-clause').trigger('click')
    await flushPromises()
    expect(api.patchFacts).toHaveBeenCalledWith(expect.objectContaining({ expectedCaseRevision: 8 }))
  })

  it('preserves edits but asks for reconciliation if the same fact changed elsewhere', async () => {
    const wrapper = await mountEditable()
    await wrapper.get('[name="appeal.form_defect"]').setValue('no')
    api.getProceduralReview.mockResolvedValue(editableReview(8, 'yes'))
    await wrapper.setProps({ caseRevision: 8 })
    await flushPromises()

    expect((wrapper.get('[name="appeal.form_defect"]').element as HTMLSelectElement).value).toBe('no')
    expect(wrapper.get('[data-clause="1"]').text()).toContain('判定資料已被更新')
    expect(wrapper.get('[data-clause="1"] .save-clause').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-clause="1"] .reset-clause').trigger('click')
    expect((wrapper.get('[name="appeal.form_defect"]').element as HTMLSelectElement).value).toBe('yes')
  })
})
