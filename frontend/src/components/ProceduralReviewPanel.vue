<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  getProceduralReview,
  patchFacts,
  CaseApiError,
  type Article77ClauseAssessment,
  type Article77EvaluationMode,
  type Article77Outcome,
  type ProceduralFieldDefinition,
  type ProceduralInputSource,
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
const draftValues = ref<Record<number, Record<string, string>>>({})
const baselineValues = ref<Record<number, Record<string, string>>>({})
const conflicts = ref<Record<number, boolean>>({})
const saveErrors = ref<Record<number, string>>({})
const saving = ref<number | null>(null)
let loadSequence = 0

const assessmentsByClause = computed<Record<number, Article77ClauseAssessment>>(() =>
  Object.fromEntries(
    (review.value?.clause_assessments ?? []).map((assessment) => [
      assessment.clause_no,
      assessment,
    ]),
  ),
)
const definitionsByPath = computed(() =>
  Object.fromEntries(
    (review.value?.field_definitions ?? []).map((field) => [field.field_path, field]),
  ),
)

function assessmentFor(clauseNo: number): Article77ClauseAssessment {
  return assessmentsByClause.value[clauseNo]!
}

function fieldsFor(clauseNo: number): ProceduralFieldDefinition[] {
  return (review.value?.field_definitions ?? []).filter((field) =>
    Object.prototype.hasOwnProperty.call(
      assessmentsByClause.value[clauseNo]?.input ?? {},
      field.field_path,
    ),
  )
}

function fieldLabel(path: string): string {
  return definitionsByPath.value[path]?.label ?? factFieldLabel(path)
}

function storedValue(clauseNo: number, path: string): string {
  const value = assessmentsByClause.value[clauseNo]?.input[path]
  return value === null || value === undefined ? '' : String(value)
}

function displayValue(clauseNo: number, field: ProceduralFieldDefinition): string {
  const value = storedValue(clauseNo, field.field_path)
  return field.options.find((option) => option.value === value)?.label ?? value
}

function sourceFor(clauseNo: number, path: string): ProceduralInputSource | undefined {
  return assessmentsByClause.value[clauseNo]?.input_sources?.[path]
}

function sourceLabel(source: ProceduralInputSource | undefined): string {
  if (!source) return '待確認來源'
  if (source.origin === 'human') return '人工填寫'
  if (source.origin === 'program') return '文件擷取'
  if (source.origin === 'ai' || source.origin === 'llm') return '自動分析'
  return '案件資料'
}

function sourceExcerpt(source: ProceduralInputSource | undefined): string {
  const detail = source?.source
  if (!detail || typeof detail !== 'object') return ''
  const record = detail as Record<string, unknown>
  const excerpt = record.excerpt ?? record.quote
  return typeof excerpt === 'string' ? excerpt : ''
}

const OUTCOME_LABELS: Record<Article77Outcome, string> = {
  NOT_TRIGGERED: '未觸發',
  TRIGGERED: '可能成立',
  NOT_APPLICABLE: '本款不適用',
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
  rule: '規則判定',
  mock: '初步檢核',
  manual_review: '人工判斷',
}

function resetClause(clauseNo: number) {
  const values = Object.fromEntries(
    fieldsFor(clauseNo).map((field) => [field.field_path, storedValue(clauseNo, field.field_path)]),
  )
  draftValues.value[clauseNo] = { ...values }
  baselineValues.value[clauseNo] = { ...values }
  conflicts.value[clauseNo] = false
  saveErrors.value[clauseNo] = ''
}

function syncDraftValues() {
  for (const assessment of review.value?.clause_assessments ?? []) {
    const clauseNo = assessment.clause_no
    if (!draftValues.value[clauseNo]) {
      resetClause(clauseNo)
      continue
    }
    for (const field of fieldsFor(clauseNo)) {
      const path = field.field_path
      const latest = storedValue(clauseNo, path)
      const baseline = baselineValues.value[clauseNo]?.[path] ?? ''
      const draft = draftValues.value[clauseNo]![path] ?? ''
      if (draft !== baseline) {
        // Keep unfinished edits, but do not silently overwrite another editor's change.
        if (latest !== baseline) conflicts.value[clauseNo] = true
      } else {
        draftValues.value[clauseNo]![path] = latest
        baselineValues.value[clauseNo]![path] = latest
      }
    }
  }
}

async function load() {
  const sequence = ++loadSequence
  loading.value = true
  loadError.value = ''
  try {
    const next = await getProceduralReview(props.caseId)
    if (sequence !== loadSequence) return
    review.value = next
    syncDraftValues()
  } catch (err) {
    if (sequence !== loadSequence) return
    loadError.value = err instanceof CaseApiError ? err.message : '無法讀取程序審查'
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

watch(
  () => [props.caseId, props.caseRevision] as const,
  ([caseId], previous) => {
    if (!previous || previous[0] !== caseId) {
      review.value = null
      draftValues.value = {}
      baselineValues.value = {}
      conflicts.value = {}
      saveErrors.value = {}
    }
    void load()
  },
  { immediate: true },
)

function changesFor(clauseNo: number) {
  return fieldsFor(clauseNo)
    .filter(
      (field) =>
        (draftValues.value[clauseNo]?.[field.field_path] ?? '') !==
        (baselineValues.value[clauseNo]?.[field.field_path] ?? ''),
    )
    .map((field) => ({
      fieldPath: field.field_path,
      value: draftValues.value[clauseNo]?.[field.field_path]?.trim() || null,
    }))
}

async function saveClause(clauseNo: number) {
  const fieldChanges = changesFor(clauseNo)
  if (!fieldChanges.length || saving.value !== null || loading.value || conflicts.value[clauseNo])
    return
  const caseId = props.caseId
  saving.value = clauseNo
  saveErrors.value[clauseNo] = ''
  try {
    const result = await patchFacts({
      caseId,
      expectedCaseRevision: review.value?.case_revision ?? props.caseRevision,
      reason: `人工更新第 ${clauseNo} 款程序審查判定資料`,
      fieldChanges,
    })
    if (props.caseId !== caseId) return
    for (const change of fieldChanges) {
      draftValues.value[clauseNo]![change.fieldPath] = change.value ?? ''
      baselineValues.value[clauseNo]![change.fieldPath] = change.value ?? ''
    }
    if (review.value) review.value.case_revision = result.case_revision
    emit('facts-updated')
    await load()
  } catch (err) {
    if (props.caseId !== caseId) return
    saveErrors.value[clauseNo] = err instanceof CaseApiError ? err.message : '儲存失敗，請稍後重試'
    if (err instanceof CaseApiError && err.status === 409) await load()
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

const riskNote = computed(() =>
  review.value?.status === 'overdue'
    ? '第 2 款期間試算顯示已逾期，屬程序風險提示；是否影響本案結果由承辦人與訴願審議委員會決定，系統不做最終判斷。'
    : '',
)
</script>

<template>
  <div class="panel review-panel">
    <div class="review-head">
      <h2>訴願法第 77 條・程序審查（八款）</h2>
      <el-tag size="small" type="info" effect="plain">未經法律覆核</el-tag>
    </div>
    <p class="review-intro">
      依目前案件資料逐款檢核；「未觸發」表示目前資料未符合該款條件。
      可展開各款補充或修改判定資料，儲存後立即重新判定。文件擷取內容仍需核對原件。
    </p>
    <el-alert v-if="loadError" type="error" show-icon :closable="false">{{ loadError }}</el-alert>
    <div v-if="loading && !review" class="loading">判定中…</div>

    <template v-if="review">
      <div class="clause-list">
        <article
          v-for="clause in ARTICLE_77_CLAUSES"
          :key="clause.no"
          :data-clause="clause.no"
          class="clause-row"
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
                <strong>判定規則：</strong
                >{{ productAssessmentText(assessmentFor(clause.no).rule_description) }}
              </p>
              <p class="assessment-reason">
                <strong>判定理由：</strong
                >{{ productAssessmentText(assessmentFor(clause.no).reason) }}
              </p>
              <p v-if="assessmentFor(clause.no).missing_fields?.length" class="missing-hint">
                尚缺：{{ assessmentFor(clause.no).missing_fields?.map(fieldLabel).join('、') }}
              </p>

              <div class="evidence-list">
                <template v-for="field in fieldsFor(clause.no)" :key="field.field_path">
                  <div v-if="storedValue(clause.no, field.field_path)" class="evidence-item">
                    <span class="evidence-label">{{ field.label }}：</span>
                    <span>{{ displayValue(clause.no, field) }}</span>
                    <span class="source-label">{{
                      sourceLabel(sourceFor(clause.no, field.field_path))
                    }}</span>
                    <blockquote v-if="sourceExcerpt(sourceFor(clause.no, field.field_path))">
                      {{ sourceExcerpt(sourceFor(clause.no, field.field_path)) }}
                    </blockquote>
                  </div>
                </template>
              </div>

              <details v-if="fieldsFor(clause.no).length" class="clause-editor">
                <summary>
                  補充／修改判定資料<span v-if="changesFor(clause.no).length"> · 尚未儲存</span>
                </summary>
                <p class="editor-hint">僅填入已確認的內容；尚未確認的欄位請留空。</p>
                <div class="field-grid">
                  <label
                    v-for="field in fieldsFor(clause.no)"
                    :key="field.field_path"
                    class="field-edit"
                  >
                    <span>{{ field.label }}</span>
                    <select
                      v-if="field.input_type === 'select'"
                      v-model="draftValues[clause.no]![field.field_path]"
                      :name="field.field_path"
                      :disabled="saving !== null"
                    >
                      <option value="">尚未確認／清除</option>
                      <option
                        v-for="option in field.options"
                        :key="option.value"
                        :value="option.value"
                      >
                        {{ option.label }}
                      </option>
                    </select>
                    <input
                      v-else
                      v-model="draftValues[clause.no]![field.field_path]"
                      :type="field.input_type === 'date' ? 'date' : 'text'"
                      :name="field.field_path"
                      :disabled="saving !== null"
                      placeholder="尚未確認"
                    />
                    <small v-if="field.help_text">{{ field.help_text }}</small>
                  </label>
                </div>
                <p v-if="conflicts[clause.no]" class="edit-error" role="alert">
                  判定資料已被更新，未儲存的編輯仍保留。請重新載入本款資料後核對再修改。
                </p>
                <p v-if="saveErrors[clause.no]" class="edit-error" role="alert">
                  {{ saveErrors[clause.no] }}
                </p>
                <div class="editor-actions">
                  <el-button
                    type="primary"
                    size="small"
                    class="save-clause"
                    :loading="saving === clause.no"
                    :disabled="
                      loading ||
                      saving !== null ||
                      conflicts[clause.no] ||
                      !changesFor(clause.no).length
                    "
                    @click="saveClause(clause.no)"
                    >儲存並重新判定</el-button
                  >
                  <el-button
                    size="small"
                    class="reset-clause"
                    :disabled="saving !== null"
                    @click="resetClause(clause.no)"
                    >{{ conflicts[clause.no] ? '重新載入本款資料' : '取消修改' }}</el-button
                  >
                </div>
              </details>
            </template>
            <template v-else-if="clause.no === 2">
              <el-tag :type="PROCEDURAL_REVIEW_STATUS_TAG_TYPE[review.status]">
                {{ PROCEDURAL_REVIEW_STATUS_LABELS[review.status] }}
              </el-tag>
              <p class="rule-description">{{ review.statute_basis }}</p>
            </template>
            <p v-else class="assessment-reason">尚未取得本款判定，請重新整理案件。</p>
            <ul v-if="clause.no === 2" class="caveats">
              <li v-for="caveat in review.caveats" :key="caveat">{{ caveat }}</li>
            </ul>
          </div>
        </article>
      </div>
      <el-alert v-if="riskNote" type="warning" show-icon :closable="false" class="risk-note">
        {{ riskNote }}
      </el-alert>
      <div class="system-disclaimer">
        <strong>本系統不做決定。</strong>
        判定依據為目前文件擷取與人工填寫的資料；是否符合各款法律要件，仍由承辦人與訴願審議委員會覆核。
      </div>
    </template>
  </div>
</template>

<style scoped>
.review-panel {
  margin-top: 18px;
  background: #fff;
  border: 1px solid #e3e8f0;
  border-radius: 10px;
  padding: 16px;
}
.review-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.review-head h2 {
  font-size: 14px;
  font-weight: 700;
  color: #16233f;
  margin: 0;
}
.review-intro,
.loading {
  color: #6b7686;
  font-size: 12px;
  line-height: 1.7;
}
.clause-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.clause-row {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 10px;
  border: 1px solid #e3e8f0;
  border-radius: 8px;
  padding: 14px;
}
.clause-no {
  color: #254e8a;
  font-size: 14px;
  font-weight: 800;
  text-align: center;
}
.clause-title {
  font-size: 13px;
  font-weight: 700;
  color: #16233f;
  margin: 0 0 10px;
}
.status-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.deadline,
.days {
  font-size: 12px;
  color: #16233f;
}
.rule-description,
.assessment-reason {
  font-size: 12px;
  line-height: 1.7;
  margin: 0 0 6px;
  color: #4a5568;
}
.assessment-reason {
  color: #16233f;
}
.missing-hint {
  font-size: 12px;
  color: #986b13;
  background: #fff9e9;
  padding: 8px 10px;
  border-radius: 5px;
}
.evidence-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 10px 0;
}
.evidence-item {
  font-size: 12px;
  color: #34435b;
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.evidence-label {
  color: #6b7686;
}
.source-label {
  display: inline-block;
  margin-left: 8px;
  color: #687d9b;
  font-size: 11px;
}
blockquote {
  border-left: 2px solid #cdd9ea;
  margin: 4px 0 0;
  padding: 3px 10px;
  color: #697a91;
  white-space: pre-wrap;
}
.clause-editor {
  margin-top: 12px;
  border-top: 1px solid #edf0f5;
  padding-top: 10px;
}
.clause-editor summary {
  font-size: 12px;
  font-weight: 600;
  color: #245595;
  cursor: pointer;
}
.clause-editor summary span {
  color: #a97516;
  font-weight: 400;
}
.editor-hint {
  color: #6b7686;
  font-size: 12px;
}
.field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.field-edit {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 12px;
  color: #33435b;
}
.field-edit select,
.field-edit input {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  border: 1px solid #d5dce7;
  border-radius: 5px;
  padding: 8px;
  min-height: 34px;
  background: #fff;
  color: #16233f;
  font: inherit;
}
.field-edit select:focus,
.field-edit input:focus {
  outline: 2px solid #bed4f5;
  border-color: #6b9cdb;
}
.field-edit small {
  color: #6b7686;
  line-height: 1.5;
}
.editor-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.editor-actions .el-button + .el-button {
  margin-left: 0;
}
.edit-error {
  color: #b74738;
  font-size: 12px;
  line-height: 1.6;
}
.caveats {
  color: #7a8699;
  font-size: 11px;
  line-height: 1.6;
  margin: 10px 0 0;
  padding-left: 16px;
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
@media (max-width: 640px) {
  .field-grid {
    grid-template-columns: 1fr;
  }
  .review-panel {
    padding: 12px;
  }
  .clause-row {
    padding: 10px;
    gap: 5px;
    grid-template-columns: 22px minmax(0, 1fr);
  }
}
</style>
