<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import { checkHealth } from '@/api/client'
import { useCaseStore } from '@/stores/case'
import AppHeader from '@/components/AppHeader.vue'
import StepNav from '@/components/StepNav.vue'

const route = useRoute()
const caseStore = useCaseStore()

const isLegacyWizard = computed(() => route.name === 'wizard')

const geminiOn = ref(false)
const apiReachable = ref(false)
const statusText = ref('')

async function checkLegacyHealth() {
  statusText.value = '連線檢查中…'
  try {
    const health = await checkHealth()
    apiReachable.value = true
    geminiOn.value = health.gemini
    statusText.value = health.gemini ? 'Gemini 已連線' : '未設定 API key（BM25 檢索）'
  } catch {
    apiReachable.value = false
    statusText.value = '無法連線到後端'
  }
}

onMounted(() => {
  if (isLegacyWizard.value) checkLegacyHealth()
})
watch(isLegacyWizard, (isLegacy) => {
  if (isLegacy) checkLegacyHealth()
})

const subtitle = computed(() => {
  if (!isLegacyWizard.value) return undefined
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
    :status-text="isLegacyWizard ? statusText : undefined"
    :status-tone="statusTone"
    :show-legacy-badge="isLegacyWizard"
  />
  <StepNav v-if="isLegacyWizard" />
  <RouterView />
</template>
