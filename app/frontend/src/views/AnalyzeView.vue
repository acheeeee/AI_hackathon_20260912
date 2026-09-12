<script setup lang="ts">
import { useCaseStore } from '@/stores/case'
import type { AnalyzeParams } from '@/api/client'
import IntakePanel from '@/components/IntakePanel.vue'
import AppealSummaryCard from '@/components/AppealSummaryCard.vue'
import StatuteList from '@/components/StatuteList.vue'
import SimilarCaseList from '@/components/SimilarCaseList.vue'
import DraftPanel from '@/components/DraftPanel.vue'

const caseStore = useCaseStore()

function handleSubmit(params: AnalyzeParams) {
  caseStore.runAnalyze(params)
}

async function handleDownload() {
  try {
    await caseStore.downloadDocx()
  } catch {
    caseStore.draftError = '下載失敗，請先生成草稿。'
  }
}
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <IntakePanel :loading="caseStore.analyzing" @submit="handleSubmit" />
    </aside>

    <main class="content">
      <el-alert v-if="caseStore.analyzeError" type="error" show-icon :closable="false">
        {{ caseStore.analyzeError }}
      </el-alert>

      <el-empty v-else-if="!caseStore.hasResult" description="請於左側上傳訴願書 PDF 或貼上文字，再按「開始分析」。" />

      <template v-else-if="caseStore.result">
        <AppealSummaryCard :appeal="caseStore.result.appeal" />
        <StatuteList
          :statutes="caseStore.result.statutes"
          :refs="caseStore.result.refs"
          :timeliness="caseStore.result.timeliness"
        />
        <SimilarCaseList :cases="caseStore.result.similar" :distribution="caseStore.result.distribution" />
        <DraftPanel
          :draft="caseStore.draft"
          :generating="caseStore.draftGenerating"
          :error="caseStore.draftError"
          @generate="caseStore.runDraft"
          @download="handleDownload"
        />
      </template>
    </main>
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: 20px;
  align-items: start;
}

.sidebar {
  position: sticky;
  top: 20px;
}

.content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

@media (max-width: 960px) {
  .layout {
    grid-template-columns: 1fr;
  }

  .sidebar {
    position: static;
  }
}
</style>
