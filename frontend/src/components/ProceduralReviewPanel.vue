<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getProceduralReview,
  patchFacts,
  CaseApiError,
  type ProceduralReview,
} from '@/api/caseapi'
import {
  factFieldLabel,
  PROCEDURAL_REVIEW_STATUS_LABELS,
  PROCEDURAL_REVIEW_STATUS_TAG_TYPE,
} from '@/utils/factLabels'

const props = defineProps<{ caseId: string; caseRevision: number }>()
const emit = defineEmits<{ (e: 'facts-updated'): void }>()

const review = ref<ProceduralReview | null>(null)
const loading = ref(true)
const loadError = ref('')
const draftValues = ref<Record<string, string>>({})
const saving = ref<string | null>(null)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    review.value = await getProceduralReview(props.caseId)
  } catch (err) {
    loadError.value = err instanceof CaseApiError ? err.message : '無法讀取程序審查'
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.caseId, load)

async function saveMissingField(fieldPath: string) {
  const value = draftValues.value[fieldPath]
  if (!value) return
  saving.value = fieldPath
  try {
    await patchFacts({
      caseId: props.caseId,
      expectedCaseRevision: props.caseRevision,
      reason: `人工補值：${factFieldLabel(fieldPath)}`,
      fieldPath,
      value,
    })
    emit('facts-updated')
    await load()
  } catch (err) {
    ElMessage.error(err instanceof CaseApiError ? err.message : '儲存失敗')
  } finally {
    saving.value = null
  }
}

function daysLabel(days: number): string {
  if (days > 0) return `已逾期 ${days} 天`
  if (days === 0) return '剛好在期限當天'
  return `距期限還有 ${-days} 天`
}
</script>

<template>
  <div class="panel review-panel">
    <div class="review-head">
      <h2>程序審查</h2>
      <el-tag size="small" type="info" effect="plain">未經法律覆核</el-tag>
    </div>

    <el-alert v-if="loadError" type="error" show-icon :closable="false">
      {{ loadError }}
    </el-alert>
    <div v-else-if="loading" class="loading">試算中…</div>

    <template v-else-if="review">
      <div class="status-row">
        <el-tag :type="PROCEDURAL_REVIEW_STATUS_TAG_TYPE[review.status]">
          {{ PROCEDURAL_REVIEW_STATUS_LABELS[review.status] }}
        </el-tag>
        <span v-if="review.deadline_date" class="deadline">
          期限：{{ review.deadline_date }}
        </span>
        <span v-if="review.days_from_deadline !== null" class="days">
          {{ daysLabel(review.days_from_deadline) }}
        </span>
      </div>

      <p class="basis">{{ review.statute_basis }}</p>

      <div v-if="review.missing_fields.length" class="missing">
        <p class="missing-hint">缺少以下欄位才能繼續試算：</p>
        <div v-for="path in review.missing_fields" :key="path" class="missing-row">
          <span class="missing-label">{{ factFieldLabel(path) }}</span>
          <el-date-picker
            v-model="draftValues[path]"
            type="date"
            value-format="YYYY-MM-DD"
            size="small"
            placeholder="選擇日期"
          />
          <el-button
            size="small"
            type="primary"
            :loading="saving === path"
            :disabled="!draftValues[path]"
            @click="saveMissingField(path)"
          >
            儲存
          </el-button>
        </div>
      </div>

      <ul class="caveats">
        <li v-for="caveat in review.caveats" :key="caveat">⚠️ {{ caveat }}</li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.review-panel {
  margin-top: 18px;
  background: #ffffff;
  border: 1px solid #e3e8f0;
  border-radius: 10px;
  padding: 16px;
}

.review-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.review-head h2 {
  font-size: 14px;
  font-weight: 700;
  color: #16233f;
  margin: 0;
}

.loading {
  color: #6b7686;
  font-size: 13px;
}

.status-row {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.deadline,
.days {
  font-size: 13px;
  color: #16233f;
}

.basis {
  font-size: 12px;
  color: #7a8699;
  line-height: 1.6;
  margin: 0 0 12px;
}

.missing {
  background: #f7f9fc;
  border: 1px solid #eef1f6;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}

.missing-hint {
  font-size: 12px;
  color: #7a8699;
  margin: 0 0 8px;
}

.missing-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.missing-row:last-child {
  margin-bottom: 0;
}

.missing-label {
  font-size: 13px;
  color: #16233f;
  min-width: 80px;
}

.caveats {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.caveats li {
  font-size: 11px;
  color: #9aa6ba;
}
</style>
