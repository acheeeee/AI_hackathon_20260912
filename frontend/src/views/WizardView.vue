<script setup lang="ts">
import { useCaseStore } from '@/stores/case'
import UploadStep from '@/views/steps/UploadStep.vue'
import ExtractStep from '@/views/steps/ExtractStep.vue'
import GateStep from '@/views/steps/GateStep.vue'
import SelectStep from '@/views/steps/SelectStep.vue'
import DraftStep from '@/views/steps/DraftStep.vue'

const caseStore = useCaseStore()
</script>

<template>
  <UploadStep v-if="caseStore.step === 'upload'" />
  <ExtractStep v-else-if="caseStore.step === 'extract'" />
  <GateStep v-else-if="caseStore.step === 'gate'" />
  <SelectStep v-else-if="caseStore.step === 'select'" />
  <DraftStep v-else-if="caseStore.step === 'draft'" />
</template>
