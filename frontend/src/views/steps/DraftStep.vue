<script setup lang="ts">
import { onMounted, computed, ref, nextTick, watch } from 'vue'
import { normalizeLegalText } from '@/utils/legalText'
import { useCaseStore } from '@/stores/case'

const caseStore = useCaseStore()

const draft = computed(() => caseStore.draft)
const appeal = computed(() => caseStore.result?.appeal ?? null)
const downloadError = ref('')

const modeTag = computed(() =>
  draft.value?.mode === 'llm'
    ? { text: 'AI 生成', cls: 'og-amber' }
    : { text: '模板', cls: 'og-muted' },
)

onMounted(() => {
  if (!caseStore.draft && !caseStore.draftGenerating) caseStore.runDraft()
})

// 依內容自動調整 textarea 高度，讓它看起來像文件而非輸入框。
function autoGrow(el: HTMLTextAreaElement) {
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight}px`
}

function growAll() {
  document.querySelectorAll<HTMLTextAreaElement>('.editor').forEach(autoGrow)
}

watch(
  () => draft.value,
  () => nextTick(growAll),
)

function onEdit(e: Event) {
  caseStore.markDirty()
  autoGrow(e.target as HTMLTextAreaElement)
}

function restoreSystem() {
  const d = caseStore.draft
  if (!d) return
  caseStore.editableMain = d.main
  caseStore.editableFact = normalizeLegalText(d.fact)
  caseStore.editableReason = normalizeLegalText(d.reason)
  caseStore.draftDirty = false
  nextTick(growAll)
}

function regenerate() {
  caseStore.runDraft()
}

async function download() {
  downloadError.value = ''
  try {
    await caseStore.downloadDocx()
  } catch {
    downloadError.value = '下載失敗，請先生成草稿。'
  }
}

function backToSelect() {
  caseStore.goTo('select')
}

const modeLabel = computed(() =>
  draft.value?.mode === 'llm' ? 'LLM 生成（需逐段確認）' : '模板＋槽位（模型不寫字）',
)

// 勾選的法條，供右欄「逐段依據」呈現（皆為真實勾選結果）。
const selectedStatuteList = computed(() => {
  const res = caseStore.result
  if (!res) return []
  return res.statutes.filter((s) => caseStore.isStatuteOn(s))
})
</script>

<template>
  <div class="page grid">
    <section class="doc-col card">
      <div class="doc-top">
        <div class="doc-title">新北市政府訴願決定書</div>
        <div class="doc-meta">
          訴願人　{{ appeal?.appellant || '—' }}　·　原處分機關　{{ appeal?.original_authority || '—' }}
          <template v-if="appeal?.disposition_no">　·　{{ appeal.disposition_no }}</template>
        </div>
      </div>

      <div class="toolbar">
        <span class="pill" :class="draft?.mode === 'llm' ? 'pill-amber' : 'pill-muted'">
          {{ modeLabel }}
        </span>
        <div class="tools">
          <button class="btn btn-line small" :disabled="caseStore.draftGenerating" @click="regenerate">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" />
            </svg>
            重新生成
          </button>
          <button class="btn btn-ghost small" @click="download">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="m7 10 5 5 5-5" />
              <path d="M12 15V3" />
            </svg>
            下載 Word
          </button>
        </div>
      </div>

      <el-alert v-if="downloadError" type="error" :closable="false" show-icon class="dl-err">
        {{ downloadError }}
      </el-alert>

      <div v-if="caseStore.draftGenerating" class="loading">
        <el-icon class="is-loading"><i /></el-icon>
        草稿生成中……
      </div>

      <el-alert
        v-else-if="caseStore.draftError"
        type="error"
        :closable="false"
        show-icon
        class="dl-err"
      >
        {{ caseStore.draftError }}
      </el-alert>

      <template v-else-if="draft">
        <div class="edit-hint">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
          </svg>
          三段內容可直接點擊修改，斷句已自動整理。修改後按「下載 Word」即匯出你編輯的版本。
          <span v-if="caseStore.draftDirty" class="dirty">· 已修改</span>
        </div>

        <div class="sec fill-bg">
          <div class="sh">主文<span class="og" :class="modeTag.cls">{{ modeTag.text }}</span></div>
          <textarea
            v-model="caseStore.editableMain"
            class="sb editor strong"
            rows="1"
            @input="onEdit"
          />
        </div>

        <div class="sec editing">
          <div class="edit-tag">編輯中</div>
          <div class="sh">
            理由<span class="og og-blue">系統填入</span>
            <span class="og-note">可自由修改，匯出以你的版本為準</span>
          </div>
          <textarea
            v-model="caseStore.editableReason"
            class="sb editor"
            rows="6"
            @input="onEdit"
          />
        </div>

        <div class="sec fill-bg">
          <div class="sh">事實<span class="og" :class="modeTag.cls">{{ modeTag.text }}</span></div>
          <textarea
            v-model="caseStore.editableFact"
            class="sb editor"
            rows="3"
            @input="onEdit"
          />
        </div>

        <div class="doc-tools">
          <button class="mini" @click="restoreSystem">還原系統版本</button>
          <span class="mini-note">你的修改僅存在本機瀏覽器，重新生成或還原會覆蓋。</span>
        </div>

        <div class="note note-amber">
          本草稿由系統依規則與模板組出（模式：{{ modeLabel }}），未經審議委員會審議，不具法律效力。所有段落均須承辦人逐段確認後始得陳核。
        </div>
      </template>
    </section>

    <aside class="side-col">
      <div class="card">
        <div class="basis-tabs">
          <span class="tab on">逐段依據</span>
          <span class="tab">八款檢核</span>
          <span class="tab">稽核紀錄</span>
        </div>
        <div class="basis-body">
          <div class="er">
            <div class="er-k">主文</div>
            <div class="er-v muted">固定文字，不引法條</div>
          </div>
          <div class="er hi">
            <div class="er-k blue">理由（勾選法條）</div>
            <div class="er-v">
              <div class="chips">
                <span v-for="s in selectedStatuteList" :key="`${s.source}:${s.doc_id}`" class="chip">
                  {{ s.statute_name }} {{ s.article_no }}
                </span>
                <span v-if="!selectedStatuteList.length" class="muted">尚未勾選法條</span>
              </div>
            </div>
          </div>
          <div class="er">
            <div class="er-k">事實</div>
            <div class="er-v muted">由擷取欄位帶入，逐格可回溯</div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="stat-title">已勾選依據統計</div>
        <div class="stat-rows">
          <div class="stat-row">
            <span class="og og-blue">法條</span>
            <div class="bar"><div class="fill blue" :style="{ width: '100%' }" /></div>
            <span class="stat-n">{{ caseStore.selectedCounts.statutes }}</span>
          </div>
          <div class="stat-row">
            <span class="og og-ok">函釋</span>
            <div class="bar"><div class="fill ok" :style="{ width: '100%' }" /></div>
            <span class="stat-n">{{ caseStore.selectedCounts.refs }}</span>
          </div>
          <div class="stat-row">
            <span class="og og-muted">前例</span>
            <div class="bar"><div class="fill grey" :style="{ width: '100%' }" /></div>
            <span class="stat-n">{{ caseStore.selectedCounts.similar }}</span>
          </div>
        </div>
        <p class="stat-note">
          草稿理由欄僅引用勾選的依據。{{
            draft?.mode === 'llm'
              ? 'LLM 模式下語言由模型組織，事實與法條仍以勾選內容為準。'
              : '模板模式下模型不寫字，全部來自模板與槽位。'
          }}
        </p>
      </div>

      <div class="card">
        <div class="stat-title">匯出</div>
        <button class="export-row" @click="download">
          <span>決定書草稿　.docx</span><span class="dl">下載</span>
        </button>
        <button class="link-back" @click="backToSelect">上一步：法條與前例</button>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 20px;
  align-items: start;
}

.doc-col {
  padding: 30px 34px 34px;
}

.side-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.doc-top {
  text-align: center;
  padding-bottom: 16px;
  border-bottom: 3px solid var(--blue);
  margin-bottom: 14px;
}

.doc-title {
  font-family: var(--font-serif);
  font-size: 21px;
  font-weight: 600;
  color: var(--blue);
  letter-spacing: 2px;
}

.doc-meta {
  font-size: 12px;
  color: var(--muted);
  margin-top: 6px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.tools {
  display: flex;
  gap: 9px;
}

.small {
  font-size: 14px;
  padding: 9px 16px;
}

.dl-err {
  margin-bottom: 12px;
  border-radius: var(--radius-sm);
}

.loading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--muted);
  padding: 40px 0;
  justify-content: center;
}

.sec {
  padding: 14px 18px;
  border-radius: var(--radius-md);
  position: relative;
  margin-bottom: 6px;
}

.fill-bg {
  background: #fafcff;
}

.editing {
  border: 2px solid var(--blue-light);
  background: #ffffff;
  box-shadow: var(--shadow);
  margin: 14px 0;
}

.edit-tag {
  position: absolute;
  top: -11px;
  left: 16px;
  background: var(--blue-light);
  color: #ffffff;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 10px;
}

.sh {
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 700;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 7px;
  flex-wrap: wrap;
}

.og {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 8px;
  border-radius: 10px;
}

.og-muted {
  background: var(--bg);
  color: var(--muted);
}

.og-blue {
  background: var(--tint);
  color: var(--blue);
}

.og-ok {
  background: var(--ok-bg);
  color: var(--ok);
}

.og-note {
  font-weight: 400;
  color: var(--muted);
}

.sb {
  font-family: var(--font-serif);
  font-size: 15px;
  line-height: 2;
  color: var(--ink);
}

.sb.strong {
  font-weight: 600;
}

.editor {
  display: block;
  width: 100%;
  border: none;
  background: transparent;
  resize: none;
  overflow: hidden;
  padding: 2px 0;
  color: var(--ink);
  font-family: var(--font-serif);
  font-size: 15px;
  line-height: 2;
  border-radius: 4px;
  transition: background 0.15s;
}

.editor:hover {
  background: rgba(11, 61, 145, 0.03);
}

.editor:focus {
  outline: none;
  background: var(--tint);
  box-shadow: inset 0 0 0 1px var(--line);
}

.edit-hint {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--blue-light);
  background: var(--tint);
  border-radius: var(--radius-sm);
  padding: 9px 12px;
  margin-bottom: 12px;
}

.dirty {
  color: var(--warn);
  font-weight: 700;
}

.doc-tools {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 12px 0 4px;
  padding-top: 12px;
  border-top: 1px dashed var(--line);
  flex-wrap: wrap;
}

.mini {
  font-size: 12px;
  font-weight: 700;
  color: var(--blue);
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 5px 12px;
  background: #ffffff;
  cursor: pointer;
  font-family: inherit;
}

.mini-note {
  font-size: 12px;
  color: var(--muted);
}

.og-amber {
  background: var(--amber-bg);
  color: var(--amber-ink);
}

.basis-tabs {
  display: flex;
  border-bottom: 1px solid var(--line);
  margin: -20px -22px 16px;
}

.tab {
  flex: 1;
  text-align: center;
  padding: 12px;
  font-size: 13px;
  color: var(--muted);
}

.tab.on {
  font-weight: 700;
  color: var(--blue);
  border-bottom: 2.5px solid var(--blue);
}

.basis-body {
  display: flex;
  flex-direction: column;
}

.er {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px dashed var(--line);
  align-items: start;
}

.er.hi {
  background: var(--tint);
  margin: 0 -8px;
  padding: 10px 8px;
  border-radius: var(--radius-sm);
}

.er-k {
  font-size: 12px;
  font-weight: 700;
  color: var(--muted);
}

.er-k.blue {
  color: var(--blue);
}

.er-v {
  font-size: 12px;
}

.muted {
  color: var(--muted);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.chip {
  font-size: 11px;
  font-weight: 700;
  background: #ffffff;
  color: var(--blue);
  padding: 2px 8px;
  border-radius: 10px;
  border: 1px solid var(--line);
}

.stat-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--blue);
  margin-bottom: 12px;
}

.stat-rows {
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.stat-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.stat-row .og {
  width: 52px;
  text-align: center;
  flex: none;
}

.bar {
  flex: 1;
  height: 7px;
  background: var(--bg);
  border-radius: 4px;
  overflow: hidden;
}

.fill {
  height: 100%;
}

.fill.blue {
  background: var(--blue);
}

.fill.ok {
  background: var(--ok);
}

.fill.grey {
  background: var(--muted);
}

.stat-n {
  font-size: 12px;
  color: var(--muted);
  width: 20px;
  text-align: right;
}

.stat-note {
  font-size: 12px;
  color: var(--muted);
  margin-top: 12px;
  line-height: 1.8;
}

.export-row {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 9px 12px;
  font-size: 13px;
  color: var(--muted);
  background: #ffffff;
  cursor: pointer;
  font-family: inherit;
}

.dl {
  font-weight: 700;
  color: var(--blue);
}

.link-back {
  border: none;
  background: transparent;
  font-family: inherit;
  font-size: 11px;
  color: var(--muted);
  cursor: pointer;
  margin-top: 12px;
  width: 100%;
}

@media (max-width: 1000px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
