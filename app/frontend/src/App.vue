<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { RouterView } from 'vue-router'
import { checkHealth } from '@/api/client'
import { useCaseStore } from '@/stores/case'
import AppHeader from '@/components/AppHeader.vue'
import StepNav from '@/components/StepNav.vue'

const caseStore = useCaseStore()

const geminiOn = ref(false)
const apiReachable = ref(false)
const statusText = ref('連線檢查中…')

onMounted(async () => {
  try {
    const health = await checkHealth()
    apiReachable.value = true
    geminiOn.value = health.gemini
    statusText.value = health.gemini ? 'Gemini 已連線' : '未設定 API key（BM25 檢索）'
  } catch {
    apiReachable.value = false
    statusText.value = '無法連線到後端'
  }
})

const subtitle = computed(() => {
  const appeal = caseStore.result?.appeal
  if (appeal?.case_type) {
    return `${appeal.appellant || '訴願人'}　·　${appeal.case_type}`
  }
  return undefined
})

const statusTone = computed<'ok' | 'plain'>(() =>
  apiReachable.value && geminiOn.value ? 'ok' : 'plain',
)
</script>

<template>
  <AppHeader
    :subtitle="subtitle"
    :gemini-on="geminiOn"
    :status-text="statusText"
    :status-tone="statusTone"
  />
  <StepNav />
  <RouterView />
</template>
