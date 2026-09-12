<script setup lang="ts">
import { ref } from 'vue'
import type { UploadFile } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import type { AnalyzeParams } from '@/api/client'

const emit = defineEmits<{
  submit: [params: AnalyzeParams]
}>()

defineProps<{
  loading: boolean
}>()

const mode = ref<'pdf' | 'text'>('pdf')
const pastedText = ref('')
const useLlm = ref(false)
const pendingFile = ref<File | null>(null)

function handleFileChange(uploadFile: UploadFile) {
  pendingFile.value = uploadFile.raw ?? null
}

function handleFileRemove() {
  pendingFile.value = null
}

function submit() {
  if (mode.value === 'pdf' && !pendingFile.value) return
  if (mode.value === 'text' && !pastedText.value.trim()) return

  emit('submit', {
    mode: mode.value,
    useLlm: useLlm.value,
    pdf: mode.value === 'pdf' ? (pendingFile.value ?? undefined) : undefined,
    text: mode.value === 'text' ? pastedText.value : undefined,
  })
}

const canSubmit = () =>
  (mode.value === 'pdf' && pendingFile.value !== null) ||
  (mode.value === 'text' && pastedText.value.trim().length > 0)
</script>

<template>
  <el-card shadow="never" class="intake-panel">
    <template #header>
      <span>📥 進件</span>
    </template>

    <el-radio-group v-model="mode" class="mode-switch">
      <el-radio-button value="pdf">上傳 PDF</el-radio-button>
      <el-radio-button value="text">貼上文字</el-radio-button>
    </el-radio-group>

    <el-upload
      v-if="mode === 'pdf'"
      drag
      accept=".pdf"
      :auto-upload="false"
      :limit="1"
      :on-change="handleFileChange"
      :on-remove="handleFileRemove"
      class="uploader"
    >
      <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
      <div class="el-upload__text">拖曳訴願書 PDF 至此，或<em>點擊選擇檔案</em></div>
    </el-upload>

    <el-input
      v-else
      v-model="pastedText"
      type="textarea"
      :rows="10"
      placeholder="貼上訴願書全文……"
    />

    <el-checkbox v-model="useLlm" class="llm-toggle">
      使用 LLM 補強爭點擷取／草稿（耗用 Gemini 額度）
    </el-checkbox>

    <el-button
      type="primary"
      size="large"
      class="submit-btn"
      :loading="loading"
      :disabled="!canSubmit()"
      @click="submit"
    >
      🚀 開始分析
    </el-button>
  </el-card>
</template>

<style scoped>
.intake-panel {
  display: flex;
  flex-direction: column;
}

.mode-switch {
  margin-bottom: 16px;
}

.uploader {
  width: 100%;
}

.llm-toggle {
  display: block;
  margin: 16px 0;
}

.submit-btn {
  width: 100%;
}
</style>
