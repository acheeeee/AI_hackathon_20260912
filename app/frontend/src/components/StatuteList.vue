<script setup lang="ts">
import type { StatuteRecommendation, TimelinessAlert } from '@/types/appeal'

defineProps<{
  statutes: StatuteRecommendation[]
  refs: StatuteRecommendation[]
  timeliness: TimelinessAlert
}>()

const sourceLabel: Record<StatuteRecommendation['source'], string> = {
  statute: '法規',
  interpretation: '行政函釋',
  precedent: '司法判解',
}
</script>

<template>
  <el-card shadow="never">
    <template #header><span>⚖️ 適用法規與時效提示</span></template>

    <el-alert
      v-if="timeliness.triggered"
      type="warning"
      :closable="false"
      show-icon
      class="alert"
    >
      {{ timeliness.message }}
    </el-alert>

    <h4>法規推薦</h4>
    <el-table :data="statutes" size="small" class="table">
      <el-table-column prop="statute_name" label="法規" width="160" />
      <el-table-column prop="article_no" label="條號" width="100" />
      <el-table-column prop="content" label="內容" show-overflow-tooltip />
      <el-table-column label="分數" width="80">
        <template #default="{ row }">{{ row.score.toFixed(3) }}</template>
      </el-table-column>
    </el-table>

    <template v-if="refs.length">
      <h4>函釋／判解</h4>
      <el-table :data="refs" size="small" class="table">
        <el-table-column label="類型" width="100">
          <template #default="{ row }: { row: StatuteRecommendation }">{{
            sourceLabel[row.source]
          }}</template>
        </el-table-column>
        <el-table-column prop="content" label="內容" show-overflow-tooltip />
        <el-table-column label="分數" width="80">
          <template #default="{ row }">{{ row.score.toFixed(3) }}</template>
        </el-table-column>
      </el-table>
    </template>
  </el-card>
</template>

<style scoped>
.alert {
  margin-bottom: 16px;
}

h4 {
  margin: 16px 0 8px;
}

.table {
  width: 100%;
}
</style>
