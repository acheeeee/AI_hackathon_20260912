<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import {
  createThread,
  sendMessage,
  getRun,
  getRunEvents,
  listMessages,
  getProposal,
  createMergePreview,
  applyProposal,
  rejectProposal,
  CaseApiError,
  type ChatIntent,
  type FactFieldTarget,
  type DraftBlockTarget,
  type TargetRef,
  type ProposalDetail,
} from '@/api/caseapi'
import { formatRunEvents } from '@/utils/runEvents'

const props = defineProps<{ caseId: string; caseRevision: number }>()
const emit = defineEmits<{ (e: 'draft-updated'): void }>()

type AssistantState = 'thinking' | 'searching' | 'done' | 'failed' | 'cancelled'
type ProposalPhase = 'idle' | 'busy' | 'accepted' | 'rejected'

interface DisplayMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  activity: string[]
  state: AssistantState | 'done'
  original?: string
  proposal?: ProposalDetail
  proposalPhase?: ProposalPhase
  conflictText?: string
  provider?: string
}

// 依後端回傳的處理方式顯示來源類別，但不暴露供應商或基礎設施細節。
const PROVIDER_LABELS: Record<string, string> = {
  fixed: '基礎規則回覆（內容請人工覆核）',
  agentcore: '線上分析（內容請人工覆核）',
}

function providerLabel(provider?: string): string {
  return provider ? (PROVIDER_LABELS[provider] ?? '自動分析（內容請人工覆核）') : ''
}

const open = ref(false)
const threadId = ref<string | null>(null)
const messages = ref<DisplayMessage[]>([])
const draft = ref('')
const sending = ref(false)
const errorText = ref('')
const scrollEl = ref<HTMLElement | null>(null)
const pendingTarget = ref<DraftBlockTarget | null>(null)
const pendingLabel = ref('')

const THINKING_LABEL: Record<AssistantState, string> = {
  thinking: '思考中…',
  searching: '查詢資料庫中…',
  done: '',
  failed: '',
  cancelled: '',
}

async function scrollToBottom() {
  await nextTick()
  scrollEl.value?.scrollTo({ top: scrollEl.value.scrollHeight })
}

async function ensureThread(): Promise<string> {
  if (threadId.value) return threadId.value
  threadId.value = await createThread(props.caseId)
  return threadId.value
}

async function pollRun(runId: string, assistantMsg: DisplayMessage) {
  const POLL_MS = 600
  const MAX_ATTEMPTS = 40
  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
    const run = await getRun(props.caseId, runId)
    if (run.state === 'completed') {
      const [events, msgs] = await Promise.all([
        getRunEvents(props.caseId, runId),
        listMessages(props.caseId, threadId.value as string),
      ])
      assistantMsg.activity = formatRunEvents(events).map((line) => line.text)
      const assistant = [...msgs].reverse().find((m) => m.role === 'assistant' && m.run_id === runId)
      assistantMsg.content = assistant?.content ?? '（沒有取得回覆）'
      assistantMsg.provider = run.provider_config?.provider
      const [proposalId] = run.proposal_ids
      if (proposalId) {
        assistantMsg.proposal = await getProposal(props.caseId, proposalId)
        assistantMsg.proposalPhase = 'idle'
      }
      assistantMsg.state = 'done'
      return
    }
    if (run.state === 'failed') {
      assistantMsg.content = '這次查詢失敗了，可以再試一次。'
      assistantMsg.state = 'failed'
      return
    }
    if (run.state === 'cancelled' || run.state === 'needs_input') {
      assistantMsg.content = run.state === 'cancelled' ? '已取消。' : '需要更多資訊才能回答。'
      assistantMsg.state = 'cancelled'
      return
    }
    assistantMsg.state = attempt < 2 ? 'thinking' : 'searching'
    await scrollToBottom()
    await new Promise((resolve) => setTimeout(resolve, POLL_MS))
  }
  assistantMsg.content = '查詢逾時，可以再試一次。'
  assistantMsg.state = 'failed'
}

async function send(content: string, intent: ChatIntent, target?: TargetRef) {
  const trimmed = content.trim()
  if (!trimmed || sending.value) return
  sending.value = true
  errorText.value = ''
  const original = target && 'selected_text' in target ? target.selected_text : undefined
  const userMsg: DisplayMessage = {
    id: `local-${Date.now()}`,
    role: 'user',
    content: trimmed,
    activity: [],
    state: 'done',
  }
  const assistantMsg: DisplayMessage = {
    id: `pending-${Date.now()}`,
    role: 'assistant',
    content: '',
    activity: [],
    state: 'thinking',
    original,
  }
  messages.value.push(userMsg, assistantMsg)
  await scrollToBottom()
  try {
    const tid = await ensureThread()
    const result = await sendMessage({
      caseId: props.caseId,
      threadId: tid,
      expectedCaseRevision: props.caseRevision,
      content: trimmed,
      intent,
      target,
    })
    await pollRun(result.run_id, assistantMsg)
  } catch (err) {
    assistantMsg.state = 'failed'
    assistantMsg.content = err instanceof CaseApiError ? err.message : '傳送失敗'
  } finally {
    sending.value = false
    await scrollToBottom()
  }
}

function submit() {
  const content = draft.value
  draft.value = ''
  if (pendingTarget.value) {
    const target = pendingTarget.value
    cancelPendingRevision()
    void send(content, 'revise_selection', target)
    return
  }
  void send(content, 'verify')
}

function askAboutField(label: string, target: FactFieldTarget) {
  open.value = true
  void send(`這個欄位「${label}」是什麼意思？`, 'explain', target)
}

function explainSelection(label: string, target: DraftBlockTarget) {
  open.value = true
  void send(`這段文字「${label}」是什麼意思？`, 'explain', target)
}

function attachSelectionForRevision(label: string, target: DraftBlockTarget) {
  open.value = true
  pendingLabel.value = label
  pendingTarget.value = target
}

function cancelPendingRevision() {
  pendingTarget.value = null
  pendingLabel.value = ''
}

function candidateText(proposal?: ProposalDetail): string {
  return proposal?.change_groups[0]?.operations[0]?.after_value ?? ''
}

async function acceptRevision(msg: DisplayMessage) {
  if (!msg.proposal || msg.proposalPhase === 'busy' || msg.proposalPhase === 'accepted') return
  msg.proposalPhase = 'busy'
  msg.conflictText = ''
  const selectedGroupIds = msg.proposal.change_groups.map((group) => group.id)
  try {
    const preview = await createMergePreview({
      caseId: props.caseId,
      proposalId: msg.proposal.proposal_id,
      expectedCaseRevision: props.caseRevision,
      selectedGroupIds,
    })
    if (!preview.can_apply) {
      msg.conflictText = '目前正文已變動，無法直接套用；請重新確認選取範圍後再試一次。'
      msg.proposalPhase = 'idle'
      return
    }
    await applyProposal({
      caseId: props.caseId,
      proposalId: msg.proposal.proposal_id,
      expectedCaseRevision: preview.current_case_revision,
      previewId: preview.preview_id,
      previewHash: preview.preview_hash,
      acceptedGroupIds: selectedGroupIds,
    })
    msg.proposalPhase = 'accepted'
    emit('draft-updated')
  } catch (err) {
    msg.proposalPhase = 'idle'
    if (err instanceof CaseApiError && err.code === 'REVISION_CONFLICT') {
      msg.conflictText = '案件已在其他操作中更新，請重新整理後再確認。'
      emit('draft-updated')
    } else {
      msg.conflictText = err instanceof CaseApiError ? err.message : '採用失敗'
    }
  }
}

async function rejectRevision(msg: DisplayMessage) {
  if (!msg.proposal || msg.proposalPhase === 'busy') return
  msg.proposalPhase = 'busy'
  try {
    await rejectProposal({
      caseId: props.caseId,
      proposalId: msg.proposal.proposal_id,
      reason: '人工拒絕此局部修改候選',
    })
    msg.proposalPhase = 'rejected'
  } catch (err) {
    msg.proposalPhase = 'idle'
    msg.conflictText = err instanceof CaseApiError ? err.message : '拒絕失敗'
  }
}

watch(open, (isOpen) => {
  if (isOpen) void scrollToBottom()
})

defineExpose({ askAboutField, explainSelection, attachSelectionForRevision, open })
</script>

<template>
  <button v-if="!open" class="toggle" @click="open = true">AI 對話</button>

  <aside class="sidebar" :class="{ open }">
    <div class="head">
      <div class="head-text">
        <span>AI 側邊欄</span>
        <span class="hint">問答與說明，不改正式內容</span>
      </div>
      <button class="close" aria-label="關閉側邊欄" @click="open = false">✕</button>
    </div>

    <div ref="scrollEl" class="thread">
      <p v-if="messages.length === 0" class="empty">
        問問題，或在左邊點一個欄位的「問 AI」。回答只會使用本案件與可回溯的法規資料。
      </p>
      <div v-for="msg in messages" :key="msg.id" class="msg" :class="msg.role">
        <div class="bubble">
          <template v-if="msg.role === 'assistant' && msg.state !== 'done' && !msg.content">
            <span class="thinking">{{ THINKING_LABEL[msg.state] }}</span>
          </template>
          <template v-else>
            {{ msg.content }}
          </template>
        </div>
        <p
          v-if="msg.role === 'assistant' && msg.provider"
          class="provider-tag"
          :class="{ offline: msg.provider === 'fixed' }"
        >
          {{ providerLabel(msg.provider) }}
        </p>
        <ul v-if="msg.activity.length" class="activity">
          <li v-for="line in msg.activity" :key="line">{{ line }}</li>
        </ul>
        <div v-if="msg.proposal" class="revision-card">
          <p class="revision-label">選取範圍的局部修改候選（未經法律覆核，尚未採用）</p>
          <p class="revision-original"><s>{{ msg.original }}</s></p>
          <p class="revision-candidate">{{ candidateText(msg.proposal) }}</p>
          <p v-if="msg.conflictText" class="revision-conflict">{{ msg.conflictText }}</p>
          <p v-if="msg.proposalPhase === 'accepted'" class="revision-done">已接受並採用到草稿正文。</p>
          <p v-else-if="msg.proposalPhase === 'rejected'" class="revision-done">已拒絕，正文未變動。</p>
          <div v-else class="revision-actions">
            <button
              type="button"
              class="accept-revision"
              :disabled="msg.proposalPhase === 'busy'"
              @click="acceptRevision(msg)"
            >
              接受
            </button>
            <button
              type="button"
              class="reject-revision"
              :disabled="msg.proposalPhase === 'busy'"
              @click="rejectRevision(msg)"
            >
              拒絕
            </button>
          </div>
        </div>
      </div>
    </div>

    <p v-if="errorText" class="err">{{ errorText }}</p>

    <div v-if="pendingTarget" class="pending-chip">
      <span>正在修改：「{{ pendingLabel }}」</span>
      <button type="button" @click="cancelPendingRevision">取消</button>
    </div>

    <form class="composer" @submit.prevent="submit">
      <input
        v-model="draft"
        :placeholder="pendingTarget ? '輸入修改指示…' : '輸入問題…'"
        :disabled="sending"
      />
      <button type="submit" :disabled="sending || !draft.trim()">送出</button>
    </form>
  </aside>
</template>

<style scoped>
.toggle {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 30;
  background: #0b3d91;
  color: #fff;
  border: none;
  border-radius: 999px;
  padding: 10px 18px;
  font-size: 13px;
  font-weight: 700;
  box-shadow: 0 6px 18px rgba(11, 61, 145, 0.35);
  cursor: pointer;
}

.sidebar {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 360px;
  background: #ffffff;
  border-left: 1px solid #e3e8f0;
  box-shadow: -6px 0 20px rgba(15, 32, 64, 0.08);
  display: flex;
  flex-direction: column;
  transform: translateX(100%);
  transition: transform 0.2s ease;
  z-index: 25;
}

.sidebar.open {
  transform: translateX(0);
}

.head {
  padding: 16px;
  border-bottom: 1px solid #eef1f6;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.head-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.head-text span:first-child {
  font-weight: 700;
  color: #16233f;
  font-size: 14px;
}

.close {
  border: none;
  background: none;
  color: #9aa6ba;
  font-size: 14px;
  cursor: pointer;
  line-height: 1;
  padding: 2px;
}

.hint {
  font-size: 11px;
  color: #9aa6ba;
}

.thread {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.empty {
  color: #9aa6ba;
  font-size: 12px;
  line-height: 1.6;
}

.msg {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.msg.user {
  align-items: flex-end;
}

.msg.assistant {
  align-items: flex-start;
}

.bubble {
  max-width: 100%;
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg.user .bubble {
  background: #0b3d91;
  color: #fff;
  border-bottom-right-radius: 2px;
}

.msg.assistant .bubble {
  background: #f3f6fc;
  color: #16233f;
  border-bottom-left-radius: 2px;
}

.thinking {
  color: #7a8699;
  font-style: normal;
}

.activity {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.activity li {
  font-size: 11px;
  color: #7a8699;
  background: #fafbfd;
  border: 1px solid #eef1f6;
  border-radius: 6px;
  padding: 4px 8px;
}

.provider-tag {
  margin: 0;
  font-size: 11px;
  color: #1a7f4b;
}

.provider-tag.offline {
  color: #b56a00;
  font-weight: 700;
}

.err {
  margin: 0 14px;
  color: #c0392b;
  font-size: 12px;
}

.revision-card {
  margin-top: 6px;
  padding: 10px;
  background: #ffffff;
  border: 1px solid #e3e8f0;
  border-radius: 8px;
  width: 100%;
}

.revision-label {
  margin: 0 0 6px;
  font-size: 11px;
  color: #7a8699;
}

.revision-original,
.revision-candidate {
  margin: 0 0 6px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.revision-original {
  color: #9aa6ba;
}

.revision-candidate {
  color: #16233f;
  background: #f3f6fc;
  border-radius: 6px;
  padding: 6px 8px;
}

.revision-conflict {
  margin: 0 0 6px;
  font-size: 11px;
  color: #b56a00;
}

.revision-done {
  margin: 0;
  font-size: 12px;
  color: #26734d;
}

.revision-actions {
  display: flex;
  gap: 8px;
}

.revision-actions button {
  border-radius: 6px;
  padding: 4px 12px;
  font-size: 12px;
  cursor: pointer;
}

.accept-revision {
  border: none;
  background: #0b3d91;
  color: #fff;
}

.reject-revision {
  border: 1px solid #d6deed;
  background: #fff;
  color: #4a5568;
}

.revision-actions button:disabled {
  opacity: 0.6;
  cursor: default;
}

.pending-chip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin: 0 12px;
  padding: 6px 10px;
  background: #eef4ff;
  border: 1px solid #c7d3e8;
  border-radius: 6px;
  font-size: 12px;
  color: #0b3d91;
}

.pending-chip button {
  border: none;
  background: none;
  color: #0b3d91;
  text-decoration: underline;
  cursor: pointer;
  font-size: 12px;
}

.composer {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid #eef1f6;
}

.composer input {
  flex: 1;
  border: 1px solid #d6deed;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
}

.composer button {
  border: none;
  background: #0b3d91;
  color: #fff;
  border-radius: 8px;
  padding: 8px 14px;
  font-size: 13px;
  cursor: pointer;
}

.composer button:disabled {
  background: #b9c6e0;
  cursor: default;
}
</style>
