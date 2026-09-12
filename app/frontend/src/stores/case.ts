import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import {
  analyzeAppeal,
  generateDraft,
  downloadDraftDocx,
  ApiError,
  type AnalyzeParams,
} from '@/api/client'
import type { AnalyzeResponse, DraftResult } from '@/types/appeal'

export const useCaseStore = defineStore('case', () => {
  const analyzing = ref(false)
  const analyzeError = ref<string | null>(null)
  const result = ref<AnalyzeResponse | null>(null)

  const draftGenerating = ref(false)
  const draftError = ref<string | null>(null)
  const draft = ref<DraftResult | null>(null)

  const hasResult = computed(() => result.value !== null)

  async function runAnalyze(params: AnalyzeParams) {
    analyzing.value = true
    analyzeError.value = null
    draft.value = null
    draftError.value = null
    try {
      result.value = await analyzeAppeal(params)
    } catch (e) {
      analyzeError.value = e instanceof ApiError ? e.message : '分析失敗，請稍後再試。'
      result.value = null
    } finally {
      analyzing.value = false
    }
  }

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
    result.value = null
    analyzeError.value = null
    draft.value = null
    draftError.value = null
  }

  return {
    analyzing,
    analyzeError,
    result,
    draftGenerating,
    draftError,
    draft,
    hasResult,
    runAnalyze,
    runDraft,
    downloadDocx,
    reset,
  }
})
