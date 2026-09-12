<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import {
  createThread,
  sendMessage,
  getRun,
  getRunEvents,
  listMessages,
  CaseApiError,
  type ChatIntent,
  type FactFieldTarget,
} from '@/api/caseapi'
import { formatRunEvents } from '@/utils/runEvents'

const props = defineProps<{ caseId: string; caseRevision: number }>()

type AssistantState = 'thinking' | 'searching' | 'done' | 'failed' | 'cancelled'

interface DisplayMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  activity: string[]
  state: AssistantState | 'done'
}

const open = ref(false)
const threadId = ref<string | null>(null)
const messages = ref<DisplayMessage[]>([])
const draft = ref('')
const sending = ref(false)
const errorText = ref('')
const scrollEl = ref<HTMLElement | null>(null)

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

async function send(content: string, intent: ChatIntent, target?: FactFieldTarget) {
  const trimmed = content.trim()
  if (!trimmed || sending.value) return
  sending.value = true
  errorText.value = ''
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
  void send(content, 'verify')
}

function askAboutField(label: string, target: FactFieldTarget) {
  open.value = true
  void send(`這個欄位「${label}」是什麼意思？`, 'explain', target)
}

watch(open, (isOpen) => {
  if (isOpen) void scrollToBottom()
})

defineExpose({ askAboutField, open })
</script>

<template>
  <button v-if="!open" class="toggle" @click="open = true">AI 對話</button>

  <aside class="sidebar" :class="{ open }">
    <div class="head">
      <div class="head-text">
        <span>AI 側邊欄</span>
        <span class="hint">verify／explain，不改正式內容</span>
      </div>
      <button class="close" aria-label="關閉側邊欄" @click="open = false">✕</button>
    </div>

    <div ref="scrollEl" class="thread">
      <p v-if="messages.length === 0" class="empty">
        問問題，或在左邊點一個欄位的「問 AI」。回答只會用本機真的查到的資料。
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
        <ul v-if="msg.activity.length" class="activity">
          <li v-for="line in msg.activity" :key="line">{{ line }}</li>
        </ul>
      </div>
    </div>

    <p v-if="errorText" class="err">{{ errorText }}</p>

    <form class="composer" @submit.prevent="submit">
      <input v-model="draft" placeholder="輸入問題…" :disabled="sending" />
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

.err {
  margin: 0 14px;
  color: #c0392b;
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
