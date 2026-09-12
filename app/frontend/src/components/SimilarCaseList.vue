<script setup lang="ts">
import type { SimilarCase, ResultDistribution } from '@/types/appeal'
import { decisionUrl } from '@/api/client'

defineProps<{
  cases: SimilarCase[]
  distribution: ResultDistribution
}>()

function openDecision(docId: string) {
  window.open(decisionUrl(docId), '_blank')
}
</script>

<template>
  <el-card shadow="never">
    <template #header><span>📚 歷史相似前例</span></template>

    <div v-if="distribution.total > 0" class="dist">
      <el-tag
        v-for="(entry, key) in distribution.distribution"
        :key="key"
        class="dist-tag"
        effect="plain"
      >
        {{ key }}：{{ entry.count }} 件（{{ (entry.ratio * 100).toFixed(0) }}%）
      </el-tag>
      <span class="dist-total">共 {{ distribution.total }} 件</span>
    </div>

    <el-empty v-if="!cases.length" description="沒有找到相似案例" />

    <el-card
      v-for="c in cases"
      :key="c.doc_id"
      shadow="hover"
      class="case-card"
      @click="openDecision(c.doc_id)"
    >
      <div class="case-head">
        <span class="case-title">{{ c.year }}年 · {{ c.case_type ?? '未分類' }}</span>
        <el-tag size="small">{{ c.result ?? '—' }}</el-tag>
        <span class="similarity">相似度 {{ (c.similarity * 100).toFixed(0) }}%</span>
      </div>
      <p v-if="c.summary" class="summary">{{ c.summary }}</p>
      <div v-if="c.shared_statutes.length" class="shared">
        共同法條：
        <el-tag v-for="s in c.shared_statutes" :key="s" size="small" type="info" class="shared-tag">
          {{ s }}
        </el-tag>
      </div>
    </el-card>
  </el-card>
</template>

<style scoped>
.dist {
  margin-bottom: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.dist-total {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.case-card {
  margin-bottom: 12px;
  cursor: pointer;
}

.case-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.case-title {
  font-weight: 600;
}

.similarity {
  color: var(--el-color-primary);
  font-size: 13px;
  margin-left: auto;
}

.summary {
  margin: 8px 0;
  color: var(--el-text-color-regular);
  line-height: 1.6;
}

.shared-tag {
  margin-right: 6px;
}
</style>
