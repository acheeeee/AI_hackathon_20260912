<script setup lang="ts">
import type { DraftResult } from '@/types/appeal'

defineProps<{
  draft: DraftResult | null
  generating: boolean
  error: string | null
}>()

const emit = defineEmits<{
  generate: []
  download: []
}>()
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="header">
        <span>📝 決定書草稿</span>
        <el-button type="primary" size="small" :loading="generating" @click="emit('generate')">
          生成草稿
        </el-button>
      </div>
    </template>

    <el-alert v-if="error" type="error" :closable="false" show-icon>{{ error }}</el-alert>

    <template v-if="draft">
      <el-tag :type="draft.mode === 'llm' ? 'success' : 'info'" class="mode-tag">
        {{ draft.mode === 'llm' ? 'LLM 生成理由欄' : '模板降級（無 API key／額度不足）' }}
      </el-tag>

      <h4>主文</h4>
      <p class="section">{{ draft.main }}</p>

      <h4>事實</h4>
      <p class="section">{{ draft.fact }}</p>

      <h4>理由</h4>
      <p class="section">{{ draft.reason }}</p>

      <el-button class="download-btn" @click="emit('download')">⬇️ 下載 Word 草稿</el-button>
    </template>

    <el-empty v-else-if="!generating" description="尚未生成草稿" />
  </el-card>
</template>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.mode-tag {
  margin-bottom: 12px;
}

h4 {
  margin: 16px 0 4px;
}

.section {
  white-space: pre-wrap;
  line-height: 1.8;
}

.download-btn {
  margin-top: 16px;
}
</style>
