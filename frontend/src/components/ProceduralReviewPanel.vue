<script setup lang="ts">
import { computed, ref, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getProceduralReview,
  patchFacts,
  CaseApiError,
  type Article77ClauseAssessment,
  type Article77EvaluationMode,
  type Article77Outcome,
  type ProceduralReview,
} from '@/api/caseapi'
import {
  factFieldLabel,
  PROCEDURAL_REVIEW_STATUS_LABELS,
  PROCEDURAL_REVIEW_STATUS_TAG_TYPE,
} from '@/utils/factLabels'
import { ARTICLE_77_CLAUSES } from '@/utils/article77'

const props = defineProps<{ caseId: string; caseRevision: number }>()
const emit = defineEmits<{ (e: 'facts-updated'): void }>()

const review = ref<ProceduralReview | null>(null)
const loading = ref(true)
const loadError = ref('')
const draftValues = ref<Record<string, string>>({})
const saving = ref<string | null>(null)

const assessmentsByClause = computed<Record<number, Article77ClauseAssessment>>(() =>
  Object.fromEntries(
    (review.value?.clause_assessments ?? []).map((assessment) => [
      assessment.clause_no,
      assessment,
    ]),
  ),
)

function assessmentFor(clauseNo: number): Article77ClauseAssessment {
  return assessmentsByClause.value[clauseNo]!
}

const OUTCOME_LABELS: Record<Article77Outcome, string> = {
  NOT_TRIGGERED: '未觸發',
  TRIGGERED: '可能成立',
  NOT_APPLICABLE: '本案不適用',
  INSUFFICIENT_EVIDENCE: '證據不足',
  NEEDS_HUMAN: '需人工覆核',
}

const OUTCOME_TAG_TYPES: Record<Article77Outcome, 'info' | 'warning' | 'success' | 'danger'> = {
  NOT_TRIGGERED: 'success',
  TRIGGERED: 'danger',
  NOT_APPLICABLE: 'info',
  INSUFFICIENT_EVIDENCE: 'warning',
  NEEDS_HUMAN: 'warning',
}

const EVALUATION_MODE_LABELS: Record<Article77EvaluationMode, string> = {
  rule: '規則試算',
  mock: '初步檢核',
  manual_review: '人工判斷',
}

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

function productAssessmentText(text: string): string {
  return text.replace(/Mock\s+規則/gi, '初步檢核').replace(/\bmock\b/gi, '初步檢核')
}

const riskNote = computed(() => {
  if (review.value?.status !== 'overdue') return ''
  return (
    '第 2 款期間試算顯示已逾期，屬程序風險提示；是否影響本案結果由承辦人與訴願審議委員會決定，' +
    '系統不做最終判斷。'
  )
})
</script>

<template>
  <div class="panel review-panel">
    <div class="review-head">
      <h2>訴願法第 77 條・程序審查（八款）</h2>
      <el-tag size="small" type="info" effect="plain">未經法律覆核</el-tag>
    </div>
    <p class="review-intro">
      條文寫的是「有左列各款情形之一者，應為不受理之決定」——任一款成立就成立，不是八款要一款一款過。
      八款都會顯示判定規則、目前狀態與理由；初步檢核只提供程序風險訊號，
      需人工判斷的款次不會被包裝成已確認的法律結論。
    </p>

    <el-alert v-if="loadError" type="error" show-icon :closable="false">
      {{ loadError }}
    </el-alert>
    <div v-else-if="loading" class="loading">試算中…</div>

    <template v-else-if="review">
      <div class="clause-list">
        <article
          v-for="clause in ARTICLE_77_CLAUSES"
          :key="clause.no"
          class="clause-row"
          :class="{ 'clause-row--rule': clause.hasRule }"
        >
          <div class="clause-no">{{ clause.no }}</div>
          <div class="clause-body">
            <p class="clause-title">{{ clause.title }}</p>

            <template v-if="assessmentsByClause[clause.no]">
              <div class="status-row">
                <el-tag :type="OUTCOME_TAG_TYPES[assessmentFor(clause.no).status]">
                  {{ OUTCOME_LABELS[assessmentFor(clause.no).status] }}
                </el-tag>
                <el-tag size="small" type="info" effect="plain">
                  {{ EVALUATION_MODE_LABELS[assessmentFor(clause.no).evaluation_mode] }}
                </el-tag>
                <span v-if="clause.no === 2 && review.deadline_date" class="deadline">
                  期限：{{ review.deadline_date }}
                </span>
                <span v-if="clause.no === 2 && review.days_from_deadline !== null" class="days">
                  {{ daysLabel(review.days_from_deadline) }}
                </span>
              </div>

              <p class="rule-description">
                <strong>判定規則：</strong>{{
                  productAssessmentText(assessmentFor(clause.no).rule_description)
                }}
              </p>
              <p class="assessment-reason">
                <strong>判定理由：</strong>{{ productAssessmentText(assessmentFor(clause.no).reason) }}
              </p>

              <div v-if="clause.no === 2 && review.missing_fields.length" class="missing">
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

              <ul v-if="clause.no === 2" class="caveats">
                <li v-for="caveat in review.caveats" :key="caveat">⚠️ {{ caveat }}</li>
              </ul>
            </template>

            <template v-else-if="clause.hasRule">
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

            <template v-else>
              <div class="clause-pending">
                <el-tag size="small" type="warning" effect="plain">待人工確認</el-tag>
                <span class="pending-note">尚無自動判定規則</span>
              </div>
              <p class="clause-hint">{{ clause.manualCheckHint }}</p>
            </template>
          </div>
        </article>
      </div>

      <el-alert v-if="riskNote" type="warning" show-icon :closable="false" class="risk-note">
        {{ riskNote }}
      </el-alert>

      <div class="system-disclaimer">
        <strong>本系統不做決定。</strong>
        八款判定、期間試算都只是提供給承辦人的材料；案件如何處理由承辦人與訴願審議委員會決定，
        每一次採用或推翻都會寫入稽核紀錄。
      </div>
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

.rule-description,
.assessment-reason {
  font-size: 12px;
  line-height: 1.7;
  margin: 0 0 6px;
}

.rule-description {
  color: #4a5568;
}

.assessment-reason {
  color: #16233f;
  margin-bottom: 10px;
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

.review-intro {
  font-size: 12px;
  color: #7a8699;
  line-height: 1.7;
  margin: 0 0 14px;
}

.clause-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.clause-row {
  display: grid;
  grid-template-columns: 28px 1fr;
  gap: 10px;
  background: #f7f9fc;
  border: 1px solid #eef1f6;
  border-radius: 8px;
  padding: 12px;
}

.clause-row--rule {
  background: #ffffff;
  border-color: #c7d3e8;
}

.clause-no {
  font-size: 13px;
  font-weight: 800;
  color: #6b7686;
  text-align: center;
}

.clause-title {
  font-size: 13px;
  font-weight: 700;
  color: #16233f;
  margin: 0 0 8px;
}

.clause-pending {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.pending-note {
  font-size: 12px;
  color: #7a8699;
}

.clause-hint {
  font-size: 12px;
  color: #6b7686;
  line-height: 1.7;
  margin: 0;
}

.risk-note {
  margin-top: 12px;
}

.system-disclaimer {
  margin-top: 14px;
  padding: 12px 14px;
  background: #fff8e1;
  border-left: 4px solid #ffd400;
  border-radius: 6px;
  font-size: 12px;
  color: #7a5c00;
  line-height: 1.8;
}
</style>
