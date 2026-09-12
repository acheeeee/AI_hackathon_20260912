<script setup lang="ts">
import type { AppealSummary } from '@/types/appeal'

defineProps<{
  appeal: AppealSummary
}>()
</script>

<template>
  <el-card shadow="never">
    <template #header><span>📋 資訊擷取與分類</span></template>
    <el-descriptions :column="2" border>
      <el-descriptions-item label="案件類型">{{ appeal.case_type ?? '—' }}</el-descriptions-item>
      <el-descriptions-item label="訴願人">{{ appeal.appellant ?? '—' }}</el-descriptions-item>
      <el-descriptions-item label="原處分機關">{{
        appeal.original_authority ?? '—'
      }}</el-descriptions-item>
      <el-descriptions-item label="原處分書文號">{{
        appeal.disposition_no ?? '—'
      }}</el-descriptions-item>
      <el-descriptions-item label="行為時（民國年）">{{
        appeal.behavior_date_roc ?? '—'
      }}</el-descriptions-item>
      <el-descriptions-item label="處分時（民國年）">{{
        appeal.disposition_date_roc ?? '—'
      }}</el-descriptions-item>
    </el-descriptions>
    <p v-if="appeal.facts" class="block"><strong>事實：</strong>{{ appeal.facts }}</p>
    <p v-if="appeal.claims" class="block"><strong>訴願人主張：</strong>{{ appeal.claims }}</p>
  </el-card>
</template>

<style scoped>
.block {
  margin-top: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
}
</style>
