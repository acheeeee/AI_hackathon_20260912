import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import {
  analyzeAppeal,
  generateDraft,
  downloadDraftDocx,
  ApiError,
  type AnalyzeParams,
} from '@/api/client'
import type { AnalyzeResponse, DraftResult, StatuteRecommendation, SimilarCase } from '@/types/appeal'

// 五步驟流程（對應 docs/design 的六張稿）：
//   1 upload  進件上傳       Main.dc.html
//   2 extract 擷取與解析     Extract.dc.html
//   3 gate    程序審查 §77   Gate.dc.html
//   4 select  法條與前例     Select.dc.html
//   5 draft   決定書草稿     Draft.dc.html
export type StepKey = 'upload' | 'extract' | 'gate' | 'select' | 'draft'

export const STEP_ORDER: StepKey[] = ['upload', 'extract', 'gate', 'select', 'draft']

export const STEP_LABELS: Record<StepKey, string> = {
  upload: '進件上傳',
  extract: '擷取與解析',
  gate: '程序審查 §77',
  select: '法條與前例',
  draft: '決定書草稿',
}

// key = `${source}:${doc_id}`，讓法條與函釋不會撞號。
function statuteKey(s: StatuteRecommendation): string {
  return `${s.source}:${s.doc_id}`
}

export const useCaseStore = defineStore('case', () => {
  // ---------- 流程狀態 ----------
  const step = ref<StepKey>('upload')

  function goTo(target: StepKey) {
    step.value = target
  }

  function next() {
    const i = STEP_ORDER.indexOf(step.value)
    const target = STEP_ORDER[i + 1]
    if (target) step.value = target
  }

  function prev() {
    const i = STEP_ORDER.indexOf(step.value)
    const target = STEP_ORDER[i - 1]
    if (target) step.value = target
  }

  // ---------- 分析 ----------
  const analyzing = ref(false)
  const analyzeError = ref<string | null>(null)
  const result = ref<AnalyzeResponse | null>(null)
  const useLlm = ref(false)

  const hasResult = computed(() => result.value !== null)

  // 勾選的依據（法條／函釋、相似前例）。預設把系統推薦的前幾筆勾起來。
  const selectedStatutes = ref<Set<string>>(new Set())
  const selectedRefs = ref<Set<string>>(new Set())
  const selectedSimilar = ref<Set<string>>(new Set())

  function toggle(set: Set<string>, key: string): Set<string> {
    const next = new Set(set)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    return next
  }

  function toggleStatute(s: StatuteRecommendation) {
    selectedStatutes.value = toggle(selectedStatutes.value, statuteKey(s))
  }

  function toggleRef(s: StatuteRecommendation) {
    selectedRefs.value = toggle(selectedRefs.value, statuteKey(s))
  }

  function toggleSimilar(c: SimilarCase) {
    selectedSimilar.value = toggle(selectedSimilar.value, c.doc_id)
  }

  function isStatuteOn(s: StatuteRecommendation) {
    return selectedStatutes.value.has(statuteKey(s))
  }

  function isRefOn(s: StatuteRecommendation) {
    return selectedRefs.value.has(statuteKey(s))
  }

  function isSimilarOn(c: SimilarCase) {
    return selectedSimilar.value.has(c.doc_id)
  }

  const selectedCounts = computed(() => ({
    statutes: selectedStatutes.value.size,
    refs: selectedRefs.value.size,
    similar: selectedSimilar.value.size,
  }))

  // 只有「有原文」的法條可勾選——零幻覺原則。
  function statuteSelectable(s: StatuteRecommendation): boolean {
    return Boolean(s.content && s.content.trim())
  }

  function seedSelections(res: AnalyzeResponse) {
    // 系統推薦：法條前 3 筆（有原文者）、函釋第 1 筆、相似前例前 2 筆預設勾選。
    const st = new Set<string>()
    res.statutes
      .filter((s) => statuteSelectable(s))
      .slice(0, 3)
      .forEach((s) => st.add(statuteKey(s)))
    selectedStatutes.value = st

    const rf = new Set<string>()
    res.refs.slice(0, 1).forEach((s) => rf.add(statuteKey(s)))
    selectedRefs.value = rf

    const sm = new Set<string>()
    res.similar.slice(0, 2).forEach((c) => sm.add(c.doc_id))
    selectedSimilar.value = sm
  }

  async function runAnalyze(params: AnalyzeParams) {
    analyzing.value = true
    analyzeError.value = null
    draft.value = null
    draftError.value = null
    useLlm.value = params.useLlm
    try {
      const res = await analyzeAppeal(params)
      result.value = res
      seedSelections(res)
      step.value = 'extract'
    } catch (e) {
      analyzeError.value = e instanceof ApiError ? e.message : '分析失敗，請稍後再試。'
      result.value = null
    } finally {
      analyzing.value = false
    }
  }

  // ---------- 草稿 ----------
  const draftGenerating = ref(false)
  const draftError = ref<string | null>(null)
  const draft = ref<DraftResult | null>(null)

  async function runDraft() {
    draftGenerating.value = true
    draftError.value = null
    try {
      draft.value = await generateDraft()
    } catch (e) {
      draftError.value = e instanceof ApiError ? e.message : '草稿生成失敗，請稍後再試。'
      draft.value = null
    } finally {
      draftGenerating.value = false
    }
  }

  async function downloadDocx() {
    const blob = await downloadDraftDocx()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'appeal_draft.docx'
    a.click()
    URL.revokeObjectURL(url)
  }

  function reset() {
    step.value = 'upload'
    result.value = null
    analyzeError.value = null
    draft.value = null
    draftError.value = null
    selectedStatutes.value = new Set()
    selectedRefs.value = new Set()
    selectedSimilar.value = new Set()
  }

  return {
    step,
    goTo,
    next,
    prev,
    analyzing,
    analyzeError,
    result,
    useLlm,
    hasResult,
    selectedStatutes,
    selectedRefs,
    selectedSimilar,
    selectedCounts,
    toggleStatute,
    toggleRef,
    toggleSimilar,
    isStatuteOn,
    isRefOn,
    isSimilarOn,
    statuteSelectable,
    runAnalyze,
    draftGenerating,
    draftError,
    draft,
    runDraft,
    downloadDocx,
    reset,
  }
})
