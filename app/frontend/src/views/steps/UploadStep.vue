<script setup lang="ts">
import { ref, computed } from 'vue'
import type { UploadFile } from 'element-plus'
import { useCaseStore } from '@/stores/case'
import { DEMO_CASES, type DemoCase } from '@/data/demoCases'

const caseStore = useCaseStore()

const primaryFile = ref<File | null>(null)
const primaryName = ref('')
const dispositionFile = ref<File | null>(null)
const dispositionName = ref('')
const useLlm = ref(false)
const selectedDemo = ref<DemoCase | null>(null)

function onPrimaryChange(f: UploadFile) {
  primaryFile.value = f.raw ?? null
  primaryName.value = f.name
  selectedDemo.value = null
}

function clearPrimary() {
  primaryFile.value = null
  primaryName.value = ''
}

function onDispositionChange(f: UploadFile) {
  dispositionFile.value = f.raw ?? null
  dispositionName.value = f.name
  selectedDemo.value = null
}

function clearDisposition() {
  dispositionFile.value = null
  dispositionName.value = ''
}

function pickDemo(demo: DemoCase) {
  selectedDemo.value = demo
  clearPrimary()
  clearDisposition()
}

const canStart = computed(() => primaryFile.value !== null || selectedDemo.value !== null)

function start() {
  if (primaryFile.value) {
    caseStore.runAnalyze({
      mode: 'pdf',
      useLlm: useLlm.value,
      pdf: primaryFile.value,
      pdf2: dispositionFile.value ?? undefined,
    })
  } else if (selectedDemo.value) {
    caseStore.runAnalyze({ mode: 'text', useLlm: useLlm.value, text: selectedDemo.value.text })
  }
}
</script>

<template>
  <div class="page grid">
    <div class="main-col">
      <el-alert
        v-if="caseStore.analyzeError"
        type="error"
        show-icon
        :closable="false"
        class="err"
      >
        {{ caseStore.analyzeError }}
      </el-alert>

      <div class="card">
        <div class="card-title">上傳案件文件</div>

        <div class="doc-grid">
          <div class="doc-slot">
            <div class="slot-head">
              <span class="idx blue">1</span>
              <span class="slot-name">訴願書</span>
              <span class="req">必要</span>
            </div>

            <div v-if="primaryName" class="doc-loaded">
              <svg class="doc-icon" width="34" height="34" viewBox="0 0 24 24" fill="none"
                stroke="#0b3d91" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <path d="M14 2v6h6" /><path d="M9 15h6" /><path d="M9 11h3" />
              </svg>
              <div class="doc-meta">
                <div class="doc-name">{{ primaryName }}</div>
                <div class="doc-ok">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M20 6 9 17l-5-5" />
                  </svg>
                  已選取，將於解析時讀取文字層
                </div>
              </div>
              <button class="doc-x" @click="clearPrimary" aria-label="移除">✕</button>
            </div>

            <el-upload
              v-else
              drag
              accept=".pdf"
              :auto-upload="false"
              :show-file-list="false"
              :on-change="onPrimaryChange"
              class="slot-drop"
            >
              <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#b9c6e0"
                stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <path d="M7 9l5-5 5 5" /><path d="M12 4v12" />
              </svg>
              <div class="drop-hint">拖曳訴願書 PDF，或 <em>點擊選擇</em></div>
            </el-upload>
          </div>

          <div class="doc-slot">
            <div class="slot-head">
              <span class="idx blue">2</span>
              <span class="slot-name">原處分書</span>
              <span class="opt">選填</span>
            </div>

            <div v-if="dispositionName" class="doc-loaded">
              <svg class="doc-icon" width="34" height="34" viewBox="0 0 24 24" fill="none"
                stroke="#0b3d91" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <path d="M14 2v6h6" /><path d="M9 15h6" /><path d="M9 11h3" />
              </svg>
              <div class="doc-meta">
                <div class="doc-name">{{ dispositionName }}</div>
                <div class="doc-ok">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M20 6 9 17l-5-5" />
                  </svg>
                  已選取，將併入分析文本
                </div>
              </div>
              <button class="doc-x" @click="clearDisposition" aria-label="移除">✕</button>
            </div>

            <el-upload
              v-else
              drag
              accept=".pdf"
              :auto-upload="false"
              :show-file-list="false"
              :on-change="onDispositionChange"
              class="slot-drop"
            >
              <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#b9c6e0"
                stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <path d="M14 2v6h6" />
              </svg>
              <div class="drop-hint">拖曳原處分書 PDF，或 <em>點擊選擇</em></div>
            </el-upload>
          </div>
        </div>

        <div class="optional">
          <div class="slot-head">
            <span class="idx grey">3</span>
            <span class="slot-name">送達證書、委任狀、其他卷證</span>
            <span class="opt">選填</span>
            <span class="opt-note">缺送達日時，第 2 款會判為「證據不足」而非「不成立」</span>
          </div>
          <div class="slot-drop static dashed">
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#b9c6e0"
              stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <path d="M7 9l5-5 5 5" /><path d="M12 4v12" />
            </svg>
            <div class="drop-hint">附加卷證（示範環境暫不送出，僅作流程說明）</div>
          </div>
        </div>
      </div>

      <div class="action-row">
        <label class="llm">
          <input type="checkbox" v-model="useLlm" />
          <span>使用 LLM 補強爭點擷取與理由欄撰寫（耗用 Gemini 額度；關閉時降級為規則擷取＋模板草稿，流程不中斷）</span>
        </label>
        <button class="btn btn-primary" :disabled="!canStart || caseStore.analyzing" @click="start">
          <span v-if="caseStore.analyzing">解析中…</span>
          <template v-else>
            開始解析
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
              <path d="M5 12h14" /><path d="m13 6 6 6-6 6" />
            </svg>
          </template>
        </button>
      </div>
    </div>

    <aside class="side-col">
      <div class="card">
        <div class="side-title">載入示範案例</div>
        <p class="side-sub">不想上傳檔案時，直接用語料庫裡的真實決定書跑完整條流程。</p>
        <button
          v-for="demo in DEMO_CASES"
          :key="demo.id"
          type="button"
          class="demo"
          :class="{ on: selectedDemo?.id === demo.id }"
          @click="pickDemo(demo)"
        >
          <div class="demo-head">
            <span class="demo-name">{{ demo.title }}</span>
            <span class="pill" :class="`pill-${demo.clauseTone === 'muted' ? 'muted' : demo.clauseTone}`">
              {{ demo.clause }}
            </span>
          </div>
          <div class="demo-note">{{ demo.note }}</div>
        </button>
      </div>

      <div class="card">
        <div class="side-title">這個系統會做什麼</div>
        <ul class="bullets">
          <li><span class="b ok">·</span>把八款程序審查從「心裡一眼排除」變成「有紀錄的排除」</li>
          <li><span class="b ok">·</span>期間算式整條攤開，逐步可驗算</li>
          <li><span class="b ok">·</span>推薦的法條與前例都附原文出處，抽不到就留空</li>
          <li><span class="b warn">·</span><strong>系統不做決定。草稿要不要用，是承辦人與委員會的事</strong></li>
        </ul>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  /* minmax(0, …) 讓欄寬不受內容 min-content 影響：上傳長檔名時版面不位移 */
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 20px;
  align-items: start;
}

.main-col {
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-width: 0;
}

.err {
  border-radius: var(--radius-sm);
}

.doc-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
}

.doc-slot {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.slot-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.idx {
  width: 20px;
  height: 20px;
  border-radius: 6px;
  color: #ffffff;
  font-size: 11px;
  font-weight: 900;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
}

.idx.blue {
  background: var(--blue);
}

.idx.grey {
  background: var(--muted);
}

.slot-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--muted);
}

.req {
  font-size: 11px;
  font-weight: 700;
  color: var(--warn);
  background: var(--warn-bg);
  padding: 1px 7px;
  border-radius: 10px;
}

.opt {
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
  background: var(--bg);
  padding: 1px 7px;
  border-radius: 10px;
}

.opt-note {
  font-size: 12px;
  color: var(--muted);
}

.slot-drop {
  min-height: 132px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--tint);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 18px;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}

.slot-drop.static {
  background: #fafcff;
}

.slot-drop.dashed {
  border: 2px dashed var(--line-strong);
}

.slot-drop :deep(.el-upload),
.slot-drop :deep(.el-upload-dragger) {
  width: 100%;
  border: none;
  background: transparent;
  padding: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.drop-hint {
  font-size: 14px;
  color: var(--muted);
}

.drop-hint em {
  color: var(--blue-light);
  font-weight: 700;
  font-style: normal;
}

.muted-hint {
  font-size: 12px;
  text-align: center;
  line-height: 1.7;
}

.doc-loaded {
  min-height: 132px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--tint);
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px;
  /* 與上傳框同寬同高，且長檔名不得撐開欄位 */
  min-width: 0;
  width: 100%;
  box-sizing: border-box;
  overflow: hidden;
}

.doc-icon {
  flex: none;
}

.doc-meta {
  flex: 1;
  min-width: 0;
}

.doc-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--blue);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-ok {
  font-size: 12px;
  color: var(--ok);
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 5px;
}

.doc-x {
  width: 26px;
  height: 26px;
  border-radius: 7px;
  border: 1px solid var(--line);
  background: #ffffff;
  color: var(--muted);
  cursor: pointer;
  flex: none;
}

.optional {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.action-row {
  display: flex;
  align-items: center;
  gap: 16px;
}

.llm {
  flex: 1;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  color: var(--muted);
  cursor: pointer;
}

.llm input {
  margin-top: 3px;
  accent-color: var(--blue);
}

.side-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.side-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--blue);
  margin-bottom: 12px;
}

.side-sub {
  font-size: 13px;
  color: var(--muted);
  margin-bottom: 14px;
}

.demo {
  display: block;
  width: 100%;
  text-align: left;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: #ffffff;
  padding: 12px 14px;
  margin-bottom: 10px;
  cursor: pointer;
  font-family: inherit;
}

.demo.on {
  border: 1.5px solid var(--blue);
  background: var(--tint);
}

.demo-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.demo-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
}

.demo.on .demo-name {
  color: var(--blue);
}

.demo-note {
  font-size: 12px;
  color: var(--muted);
  margin-top: 5px;
}

.bullets {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 11px;
}

.bullets li {
  display: flex;
  gap: 9px;
  font-size: 13px;
  color: var(--muted);
}

.b {
  font-weight: 900;
}

.b.ok {
  color: var(--ok);
}

.b.warn {
  color: var(--warn);
}

.bullets strong {
  color: var(--warn);
  font-weight: 700;
}

@media (max-width: 960px) {
  .grid {
    grid-template-columns: 1fr;
  }
  .doc-grid {
    grid-template-columns: 1fr;
  }
}
</style>
