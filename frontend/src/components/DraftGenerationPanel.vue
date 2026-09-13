<script setup lang="ts">
// 產生草稿：選法規之後的觸發點＋處理中畫面。
// 節奏（讀取事實／查核法規原文／生成中）是前端假的時間軸，但畫面上列出的
// 「參考了哪些事實／哪些法規」全部來自後端真資料（getFacts／getStatuteSelection），
// 活動紀錄則來自真的 run 事件（formatRunEvents）。不編造任何一行。
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getFacts,
  getStatuteSelection,
  startDraftGeneration,
  getRun,
  getRunEvents,
  getProposal,
  createMergePreview,
  applyProposal,
  CaseApiError,
  type FactFieldValue,
  type SelectedStatute,
  type ProposalDetail,
  type ProposalBlock,
} from '@/api/caseapi'
import { factFieldLabel } from '@/utils/factLabels'
import { formatRunEvents } from '@/utils/runEvents'

const props = defineProps<{ caseId: string; caseRevision: number }>()
const emit = defineEmits<{
  (e: 'draft-generated'): void
  (e: 'proposal-adopted'): void
  (e: 'refresh-requested'): void
}>()

const POLL_MS = 600
const MAX_ATTEMPTS = 60
const PHASES = ['讀取事實與選定法規…', '查核法規原文中…', '生成草稿中…']

type PanelState = 'idle' | 'running' | 'done' | 'failed'

const state = ref<PanelState>('idle')
const phase = ref(PHASES[0])
const activity = ref<string[]>([])
const facts = ref<Record<string, FactFieldValue>>({})
const statutes = ref<SelectedStatute[]>([])
const proposal = ref<ProposalDetail | null>(null)
const answer = ref('')
const errorText = ref('')
const generatedCaseRevision = ref<number | null>(null)
const adopting = ref(false)
const adopted = ref(false)
const mergeConflictText = ref('')

const knownFacts = computed(() =>
  Object.entries(facts.value)
    .filter(([, field]) => field.value !== null)
    .map(([path, field]) => `${factFieldLabel(path)}：${field.value}`),
)

const canGenerate = computed(() => statutes.value.length > 0 && state.value !== 'running')

const generatedBlocks = computed<ProposalBlock[]>(() => {
  const operation = proposal.value?.change_groups[0]?.operations[0]
  return operation?.after_blocks ?? []
})

async function loadContext() {
  try {
    const [factFields, selection] = await Promise.all([
      getFacts(props.caseId),
      getStatuteSelection(props.caseId),
    ])
    facts.value = factFields
    statutes.value = selection
  } catch (err) {
    errorText.value = err instanceof CaseApiError ? err.message : '無法讀取草稿生成的依據'
  }
}

onMounted(loadContext)
watch(() => [props.caseId, props.caseRevision], loadContext)

async function pollRun(runId: string) {
  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
    const run = await getRun(props.caseId, runId)
    if (run.state === 'completed') {
      const events = await getRunEvents(props.caseId, runId)
      activity.value = formatRunEvents(events).map((line) => line.text)
      answer.value = readAnswer(events)
      const [proposalId] = run.proposal_ids
      proposal.value = proposalId ? await getProposal(props.caseId, proposalId) : null
      state.value = 'done'
      emit('draft-generated')
      return
    }
    if (run.state === 'failed' || run.state === 'cancelled') {
      errorText.value = run.state === 'failed' ? '生成失敗，可以再試一次。' : '已取消。'
      state.value = 'failed'
      return
    }
    phase.value = PHASES[Math.min(attempt, PHASES.length - 1)]
    await new Promise((resolve) => setTimeout(resolve, POLL_MS))
  }
  errorText.value = '生成逾時，可以再試一次。'
  state.value = 'failed'
}

function readAnswer(events: Awaited<ReturnType<typeof getRunEvents>>): string {
  const delta = [...events].reverse().find((event) => event.event_type === 'answer.delta')
  return typeof delta?.payload.delta === 'string' ? delta.payload.delta : ''
}

async function generate() {
  state.value = 'running'
  phase.value = PHASES[0]
  activity.value = []
  proposal.value = null
  answer.value = ''
  errorText.value = ''
  generatedCaseRevision.value = null
  adopting.value = false
  adopted.value = false
  mergeConflictText.value = ''
  try {
    const started = await startDraftGeneration({
      caseId: props.caseId,
      expectedCaseRevision: props.caseRevision,
    })
    generatedCaseRevision.value = started.case_revision
    await pollRun(started.run_id)
  } catch (err) {
    state.value = 'failed'
    errorText.value = err instanceof CaseApiError ? err.message : '無法開始生成'
    ElMessage.error(errorText.value)
  }
}

async function adopt() {
  if (!proposal.value || adopting.value || adopted.value) return

  const selectedGroupIds = proposal.value.change_groups.map((group) => group.id)
  if (!selectedGroupIds.length) return

  adopting.value = true
  mergeConflictText.value = ''
  try {
    const expectedCaseRevision = Math.max(
      props.caseRevision,
      generatedCaseRevision.value ?? props.caseRevision,
    )
    const preview = await createMergePreview({
      caseId: props.caseId,
      proposalId: proposal.value.proposal_id,
      expectedCaseRevision,
      selectedGroupIds,
    })
    if (!preview.can_apply) {
      const codes = preview.conflicts.map((conflict) => conflict.code)
      mergeConflictText.value = codes.length
        ? `目前正文或依賴資料已變動，無法直接覆蓋（${codes.join('、')}）。請保留目前內容並重新產生草稿；這一版不會自動解決衝突。`
        : '提案仍有未滿足的相依修改，現在不能採用；這一版不會沉默略過。'
      return
    }

    const result = await applyProposal({
      caseId: props.caseId,
      proposalId: proposal.value.proposal_id,
      expectedCaseRevision: preview.current_case_revision,
      previewId: preview.preview_id,
      previewHash: preview.preview_hash,
      acceptedGroupIds: selectedGroupIds,
    })
    proposal.value = { ...proposal.value, state: result.proposal_state }
    generatedCaseRevision.value = result.case_revision
    adopted.value = true
    ElMessage.success('草稿已採用，可以開始逐段編輯')
    emit('proposal-adopted')
  } catch (err) {
    const message = err instanceof CaseApiError ? err.message : '採用草稿失敗'
    if (err instanceof CaseApiError && err.code === 'REVISION_CONFLICT') {
      mergeConflictText.value = '案件已在其他操作中更新。請重新確認目前草稿後再採用。'
      emit('refresh-requested')
    } else {
      errorText.value = message
      ElMessage.error(message)
    }
  } finally {
    adopting.value = false
  }
}
</script>

<template>
  <div class="panel draft-panel">
    <h2>產生草稿</h2>

    <el-alert v-if="errorText" type="error" show-icon :closable="false">{{ errorText }}</el-alert>

    <div class="basis">
      <div class="basis-col">
        <p class="column-title">會用到的事實（{{ knownFacts.length }}）</p>
        <ul v-if="knownFacts.length" class="basis-list">
          <li v-for="line in knownFacts" :key="line">{{ line }}</li>
        </ul>
        <p v-else class="empty-hint">目前沒有已填的事實欄位。</p>
      </div>
      <div class="basis-col">
        <p class="column-title">會引用的法規（{{ statutes.length }}）</p>
        <ul v-if="statutes.length" class="basis-list">
          <li v-for="item in statutes" :key="item.chunk_id">
            {{ item.statute_name }}第{{ item.article_key }}條
          </li>
        </ul>
        <p v-else class="empty-hint">還沒選法規，請先在上面的「選法規」挑選並儲存。</p>
      </div>
    </div>

    <div class="actions">
      <el-button type="primary" :disabled="!canGenerate" :loading="state === 'running'" @click="generate">
        {{ state === 'done' ? '重新產生草稿' : '產生草稿' }}
      </el-button>
    </div>

    <div v-if="state === 'running'" class="progress">
      <p class="phase">{{ phase }}</p>
      <p class="phase-note">進度節奏是畫面效果；下面的紀錄是真的執行事件。</p>
    </div>

    <template v-if="state === 'done'">
      <p v-if="answer" class="answer">{{ answer }}</p>
      <ul v-if="activity.length" class="activity">
        <li v-for="line in activity" :key="line">{{ line }}</li>
      </ul>

      <div v-if="proposal" class="result">
        <p class="column-title">
          生成的草稿內容（提案 {{ proposal.proposal_id }}，狀態 {{ proposal.state }}）
        </p>
        <p v-if="!adopted" class="empty-hint">
          這份內容還沒寫進案件正文。按下採用前，系統會先做三方合併預覽。
        </p>
        <p v-else class="adopted-note">已採用到案件草稿正文。</p>
        <div v-for="block in generatedBlocks" :key="block.block_id" class="block">
          <p class="block-text">{{ block.text }}</p>
          <p v-if="block.citations.length" class="block-citations">
            依據：{{ block.citations.join('、') }}
          </p>
        </div>
        <el-alert
          v-if="mergeConflictText"
          class="merge-alert"
          type="warning"
          show-icon
          :closable="false"
        >
          {{ mergeConflictText }}
        </el-alert>
        <div class="actions">
          <el-button
            type="primary"
            :loading="adopting"
            :disabled="adopted || proposal.state !== 'ready'"
            @click="adopt"
          >
            {{ adopted ? '已採用' : '採用這份草稿' }}
          </el-button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.draft-panel {
  margin-top: 18px;
  background: #ffffff;
  border: 1px solid #e3e8f0;
  border-radius: 10px;
  padding: 16px;
}

.draft-panel h2 {
  font-size: 14px;
  font-weight: 700;
  color: #16233f;
  margin: 0 0 12px;
}

.basis {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.column-title {
  font-size: 12px;
  font-weight: 700;
  color: #16233f;
  margin: 0 0 8px;
}

.basis-list {
  list-style: none;
  margin: 0;
  padding: 0;
  font-size: 12px;
  color: #4a5568;
  line-height: 1.8;
}

.empty-hint {
  color: #9aa6ba;
  font-size: 12px;
  margin: 0;
}

.actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.progress {
  border-top: 1px solid #eef1f6;
  padding-top: 12px;
}

.phase {
  font-size: 13px;
  color: #0b3d91;
  margin: 0 0 4px;
}

.phase-note,
.block-citations {
  font-size: 11px;
  color: #9aa6ba;
  margin: 0;
}

.answer {
  font-size: 13px;
  color: #16233f;
  line-height: 1.7;
  margin: 12px 0 8px;
}

.activity {
  list-style: none;
  margin: 0 0 12px;
  padding: 0;
  font-size: 12px;
  color: #6b7686;
  line-height: 1.8;
}

.result {
  border-top: 1px solid #eef1f6;
  padding-top: 12px;
}

.adopted-note {
  color: #26734d;
  font-size: 12px;
  margin: 0;
}

.merge-alert {
  margin-top: 12px;
}

.block {
  background: #f7f9fc;
  border: 1px solid #eef1f6;
  border-radius: 8px;
  padding: 10px;
  margin-top: 8px;
}

.block-text {
  font-size: 13px;
  color: #16233f;
  line-height: 1.8;
  white-space: pre-wrap;
  margin: 0 0 4px;
}
</style>
