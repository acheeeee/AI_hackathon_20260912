<script setup lang="ts">
import { computed } from 'vue'
import { useCaseStore } from '@/stores/case'

const caseStore = useCaseStore()

interface FieldRow {
  key: string
  value: string | null
  source: string
  found: boolean
  highlight?: 'date' | null
}

const appeal = computed(() => caseStore.result?.appeal ?? null)

function rocDate(n: number | null): string | null {
  return n ? `民國 ${n} 年（行為／處分年度）` : null
}

const rows = computed<FieldRow[]>(() => {
  const a = appeal.value
  if (!a) return []
  return [
    { key: '訴願人', value: a.appellant, source: 'AI 擷取', found: !!a.appellant },
    { key: '原處分機關', value: a.original_authority, source: 'AI 擷取', found: !!a.original_authority },
    { key: '案件類型', value: a.case_type, source: '規則：要旨標頭', found: !!a.case_type },
    { key: '原處分文號', value: a.disposition_no, source: 'AI 擷取', found: !!a.disposition_no },
    {
      key: '行為時年度',
      value: rocDate(a.behavior_date_roc),
      source: 'AI 擷取',
      found: !!a.behavior_date_roc,
      highlight: 'date',
    },
    {
      key: '處分時年度',
      value: rocDate(a.disposition_date_roc),
      source: 'AI 擷取',
      found: !!a.disposition_date_roc,
      highlight: 'date',
    },
  ]
})

const foundCount = computed(() => rows.value.filter((r) => r.found).length)
const missingCount = computed(() => rows.value.filter((r) => !r.found).length)

// 關鍵字：以案件類型與檢索出的法規名稱組成（皆來自真實分析結果，非捏造）。
const keywords = computed<string[]>(() => {
  const res = caseStore.result
  if (!res) return []
  const set = new Set<string>()
  if (res.appeal.case_type) set.add(res.appeal.case_type)
  res.statutes.slice(0, 6).forEach((s) => set.add(s.statute_name))
  return [...set]
})

const summary = computed(() => {
  const a = appeal.value
  if (!a) return ''
  if (a.facts) return a.facts
  return [a.appellant, a.original_authority, a.case_type].filter(Boolean).join('　·　')
})

function toGate() {
  caseStore.goTo('gate')
}

function backToUpload() {
  caseStore.goTo('upload')
}
</script>

<template>
  <div class="page grid">
    <aside class="left">
      <div class="card">
        <div class="card-title">案件文件</div>
        <div class="doc active">
          <div class="doc-name">進件文本</div>
          <div class="doc-sub">已解析　·　擷取 {{ rows.length }} 欄</div>
        </div>
        <div class="src-note">
          <div class="src-label">原文對照</div>
          <p>欄位的來源標籤會標示擷取自何處；請對照原始文件確認內容。</p>
        </div>
      </div>
    </aside>

    <section class="mid card">
      <div class="mid-head">
        <div class="card-title no-border">擷取欄位</div>
        <div class="counts">
          {{ rows.length }} 欄　·　{{ foundCount }} 欄有出處　·＝
          <span class="miss">{{ missingCount }} 欄查無</span>
        </div>
      </div>

      <div class="tbl">
        <div class="row head">
          <div>欄位</div>
          <div>擷取值</div>
          <div>來源</div>
        </div>
        <div
          v-for="r in rows"
          :key="r.key"
          class="row"
          :class="{ miss: !r.found, date: r.highlight === 'date' && r.found }"
        >
          <div class="k">{{ r.key }}</div>
          <div class="v">
            <template v-if="r.found">{{ r.value }}</template>
            <span v-else class="v-miss">查無　—　不猜、不填</span>
          </div>
          <div class="s">{{ r.found ? r.source : '文本無此欄' }}</div>
        </div>
      </div>

      <div class="tbl-note">
        擷取值來自進件文本的規則解析與可選的自動分析。查無的欄位一律留空，不自行補寫，內容仍須人工覆核。
      </div>
    </section>

    <aside class="right">
      <div class="card">
        <div class="card-title">案件摘要</div>
        <p class="summary">{{ summary || '（無摘要）' }}</p>
        <div class="note note-amber">
          摘要僅呈現程序事實。實體主張於程序審查通過後才進一步擷取——先程序、後實體，是訴願法的條文結構。
        </div>
      </div>

      <div class="card">
        <div class="card-title">關鍵字</div>
        <div class="kw-wrap">
          <span v-for="(kw, i) in keywords" :key="kw" class="kw" :class="{ main: i === 0 }">
            {{ kw }}
          </span>
          <span v-if="!keywords.length" class="kw-empty">（尚無關鍵字）</span>
        </div>
        <p class="kw-note">深色為主軸關鍵字，會用於法條與前例檢索。</p>
      </div>

      <div class="card next-card">
        <p class="next-hint">確認欄位無誤後，進入程序審查。八款會一次全部跑完，不是逐款詢問。</p>
        <button class="btn btn-primary btn-block" @click="toGate">
          開始程序審查
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
            <path d="M5 12h14" /><path d="m13 6 6 6-6 6" />
          </svg>
        </button>
        <button class="link-back" @click="backToUpload">上一步：重新上傳文件</button>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: 220px 1fr 320px;
  gap: 20px;
  align-items: start;
}

.left,
.right {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.doc {
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  margin-bottom: 12px;
}

.doc.active {
  border: 1.5px solid var(--blue);
  background: var(--tint);
}

.doc-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--blue);
}

.doc-sub {
  font-size: 11px;
  color: var(--muted);
  margin-top: 2px;
}

.src-note {
  border-top: 1px dashed var(--line);
  padding-top: 12px;
}

.src-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--muted);
  margin-bottom: 6px;
}

.src-note p {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.8;
}

.no-border {
  border: none;
  padding: 0;
  margin: 0;
}

.mid-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 10px;
  border-bottom: 2px solid var(--line);
  margin-bottom: 6px;
}

.counts {
  font-size: 12px;
  color: var(--muted);
}

.miss {
  color: var(--amber-ink);
  font-weight: 700;
}

.tbl {
  display: flex;
  flex-direction: column;
}

.row {
  display: grid;
  grid-template-columns: 120px 1fr 150px;
  gap: 10px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  align-items: center;
}

.row.head {
  border-bottom: 1.5px solid var(--line);
}

.row.head > div {
  font-size: 12px;
  font-weight: 700;
  color: var(--blue);
}

.row.date {
  background: var(--tint);
  border-radius: 6px;
}

.row.miss {
  background: var(--amber-bg);
  border-radius: 6px;
}

.k {
  font-size: 12px;
  color: var(--muted);
  font-weight: 700;
}

.row.date .k {
  color: var(--blue);
}

.row.miss .k {
  color: var(--amber-ink);
}

.v {
  font-size: 13px;
  font-weight: 500;
}

.row.date .v {
  color: var(--blue);
  font-weight: 700;
}

.v-miss {
  color: var(--amber-ink);
  font-weight: 700;
}

.s {
  font-size: 11px;
  color: var(--muted);
}

.row.date .s {
  color: var(--blue);
}

.row.miss .s {
  color: var(--amber-ink);
}

.tbl-note {
  background: var(--bg);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
  margin-top: 14px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.8;
}

.summary {
  font-size: 13px;
  line-height: 1.9;
  color: var(--ink);
  margin-bottom: 12px;
}

.kw-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.kw {
  font-size: 12px;
  background: var(--tint);
  color: var(--blue);
  padding: 4px 11px;
  border-radius: 14px;
}

.kw.main {
  font-weight: 700;
  background: var(--blue);
  color: #ffffff;
}

.kw-empty {
  font-size: 12px;
  color: var(--muted);
}

.kw-note {
  font-size: 12px;
  color: var(--muted);
  margin-top: 12px;
  line-height: 1.8;
}

.next-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.next-hint {
  font-size: 13px;
  color: var(--muted);
  line-height: 1.8;
}

.link-back {
  border: none;
  background: transparent;
  font-family: inherit;
  font-size: 11px;
  color: var(--muted);
  cursor: pointer;
}

@media (max-width: 1100px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
