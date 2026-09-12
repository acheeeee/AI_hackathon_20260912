<script setup lang="ts">
import { ref, computed } from 'vue'
import { useCaseStore } from '@/stores/case'

const caseStore = useCaseStore()

type Verdict = 'pending' | 'clear' | 'triggered' | 'human' | 'na'

interface Clause {
  no: number
  title: string
  desc: string
  // 第 3、8 款屬實質法律判斷，設計稿定義為永遠「待人工」，系統不給結論。
  human?: boolean
}

const CLAUSES: Clause[] = [
  { no: 1, title: '訴願書不合法定程式不能補正，或經通知補正逾期不補正', desc: '訴願書之程式是否完備' },
  { no: 2, title: '提起訴願逾法定期間', desc: '純日期算術，見右側期間算式' },
  { no: 3, title: '訴願人不符第 18 條規定（當事人不適格）', desc: '實質法律判斷，系統不判', human: true },
  { no: 4, title: '無訴願能力人未由法定代理人代為訴願行為', desc: '訴願人能力之確認' },
  { no: 5, title: '法人或非法人團體未由代表人為訴願行為', desc: '代表人事實是否齊備' },
  { no: 6, title: '行政處分已不存在', desc: '原處分現是否仍存在' },
  { no: 7, title: '對已決定或已撤回之訴願事件重行提起', desc: '是否有前案' },
  { no: 8, title: '對非行政處分或不屬訴願救濟範圍之事項提起', desc: '實質法律判斷，系統不判', human: true },
]

// 承辦人可調整的款別判定。預設：實質判斷款為「待人工」，其餘為「待確認」。
// 說明：src/gate.py 尚未實作，八款判定目前由承辦人於介面確認，非系統自動裁決。
const verdicts = ref<Record<number, Verdict>>(
  Object.fromEntries(CLAUSES.map((c) => [c.no, c.human ? 'human' : 'pending'])),
)

const VERDICT_META: Record<Verdict, { label: string; cls: string; dot: string }> = {
  pending: { label: '待確認', cls: 'pill-muted', dot: '#b9c6e0' },
  clear: { label: '不成立', cls: 'pill-ok', dot: '#1a7f4b' },
  triggered: { label: '成立', cls: 'pill-warn', dot: '#c0392b' },
  human: { label: '待人工判斷', cls: 'pill-amber', dot: '#ffd400' },
  na: { label: '不適用', cls: 'pill-muted', dot: '#b9c6e0' },
}

function cycle(no: number) {
  const clause = CLAUSES.find((c) => c.no === no)
  if (clause?.human) return // 實質判斷款固定待人工
  const order: Verdict[] = ['pending', 'clear', 'triggered', 'na']
  const cur = verdicts.value[no] ?? 'pending'
  const idx = order.indexOf(cur)
  verdicts.value[no] = order[(idx + 1) % order.length] ?? 'pending'
}

function verdictOf(no: number): Verdict {
  return verdicts.value[no] ?? 'pending'
}

const anyTriggered = computed(() => Object.values(verdicts.value).some((v) => v === 'triggered'))

const tallies = computed(() => {
  const t = { clear: 0, triggered: 0, human: 0, na: 0, pending: 0 }
  Object.values(verdicts.value).forEach((v) => (t[v] += 1))
  return t
})

// 時效：這是後端唯一真的算出來的程序訊號（行政罰法第5條 從新從輕）。
const timeliness = computed(() => caseStore.result?.timeliness ?? null)

function toSelect() {
  caseStore.goTo('select')
}

function toDraft() {
  caseStore.goTo('draft')
}
</script>

<template>
  <div class="page grid">
    <div class="left">
      <div class="note note-blue impl-note">
        <strong>程序審查引擎（src/gate.py）尚未實作。</strong>以下八款為介面層的人工確認欄位，供承辦人逐款判定並記錄，系統目前不自動裁決各款是否成立。唯一由後端計算的程序訊號是右側「從新從輕」時效提示。
      </div>

      <div class="card">
        <div class="gate-head">
          <div>
            <div class="card-title no-border">訴願法第 77 條　八款排除性確認</div>
            <p class="gate-sub">
              條文為「有左列各款情形<strong>之一</strong>者，應為不受理之決定」。任一款成立即成立，非八關逐一過。
            </p>
          </div>
          <div class="tally">
            <span class="pill pill-ok">不成立 {{ tallies.clear }}</span>
            <span class="pill pill-warn">成立 {{ tallies.triggered }}</span>
            <span class="pill pill-amber">待人工 {{ tallies.human }}</span>
            <span class="pill pill-muted">待確認 {{ tallies.pending }}</span>
          </div>
        </div>

        <div class="clauses">
          <button
            v-for="c in CLAUSES"
            :key="c.no"
            type="button"
            class="clause"
            :class="{
              on: verdictOf(c.no) === 'triggered',
              human: verdictOf(c.no) === 'human',
              clickable: !c.human,
            }"
            @click="cycle(c.no)"
          >
            <span class="c-no" :class="{ warn: verdictOf(c.no) === 'triggered' }">{{ c.no }}</span>
            <span class="c-body">
              <span class="c-title">{{ c.title }}</span>
              <span class="c-desc">{{ c.desc }}</span>
            </span>
            <span class="pill" :class="VERDICT_META[verdictOf(c.no)].cls">
              <span class="dot" :style="{ background: VERDICT_META[verdictOf(c.no)].dot }" />
              {{ VERDICT_META[verdictOf(c.no)].label }}
            </span>
          </button>
        </div>
      </div>

      <div class="note note-blue">
        第 3、5、8 款屬實質判斷，仍待人工，但不影響「之一」的邏輯：只要任一款經你確認成立，本件即應為不受理。若無任何款成立，可進實體審查（法條與前例）。
      </div>
    </div>

    <aside class="right">
      <div class="card timeliness" :class="timeliness?.triggered ? 'tl-on' : 'tl-off'">
        <div class="tl-head">
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M10.3 3.6 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0z" />
            <path d="M12 9v4" /><path d="M12 17h.01" />
          </svg>
          <span>從新從輕　行政罰法第 5 條</span>
        </div>
        <p class="tl-msg">{{ timeliness?.message || '無時效提示資料。' }}</p>
        <div v-if="timeliness?.changed_statutes?.length" class="tl-changed">
          <span v-for="s in timeliness.changed_statutes" :key="s" class="pill pill-warn">{{ s }}</span>
        </div>
        <p class="tl-src">判定方式：比對行為時／處分時年度與法規修正年度，屬規則計算，不經語言模型。</p>
      </div>

      <div class="card verdict-card">
        <div class="v-head" :class="anyTriggered ? 'v-red' : 'v-blue'">
          <div class="v-label">程序審查結果</div>
          <div class="v-title">{{ anyTriggered ? '不受理' : '尚待承辦人確認' }}</div>
          <div class="v-sub">{{ anyTriggered ? '訴願法第 77 條（任一款成立）' : '請於左側逐款確認' }}</div>
        </div>
        <div class="v-body">
          <p class="v-hint">要不要照這個結論寫，是你的決定。系統只把款別欄位與時效算式攤開。</p>
          <button v-if="anyTriggered" class="btn btn-primary btn-block" @click="toDraft">
            產生不受理草稿
          </button>
          <button class="btn btn-ghost btn-block" @click="toSelect">進實體審查（法條與前例）</button>
        </div>
      </div>

      <div class="note note-amber">
        <strong>本系統不做決定。</strong>八款判定、時效算式、法條推薦都只是給承辦人的材料。案件的結束由承辦人與訴願審議委員會決定。
      </div>
    </aside>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: 1fr 330px;
  gap: 20px;
  align-items: start;
}

.left {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.right {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.impl-note {
  border-left-width: 4px;
}

.no-border {
  border: none;
  padding: 0;
  margin: 0;
}

.gate-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 12px;
  border-bottom: 2px solid var(--line);
  margin-bottom: 14px;
}

.gate-sub {
  font-size: 12px;
  color: var(--muted);
  margin-top: 3px;
}

.tally {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.clauses {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.clause {
  display: grid;
  grid-template-columns: 44px 1fr 128px;
  gap: 12px;
  align-items: center;
  padding: 11px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: #ffffff;
  font-family: inherit;
  text-align: left;
  cursor: default;
}

.clause.clickable {
  cursor: pointer;
}

.clause.on {
  border: 2px solid var(--warn);
  background: var(--warn-bg);
}

.clause.human {
  background: var(--amber-bg);
  border-color: var(--yellow);
}

.c-no {
  font-size: 13px;
  font-weight: 900;
  color: var(--muted);
  text-align: center;
}

.c-no.warn {
  color: var(--warn);
}

.c-title {
  display: block;
  font-size: 13px;
  font-weight: 700;
}

.c-desc {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-top: 2px;
}

.clause .pill {
  justify-content: center;
}

.timeliness {
  border-top: 3px solid var(--yellow);
}

.tl-on {
  background: var(--warn-bg);
}

.tl-head {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 15px;
  font-weight: 700;
  color: var(--warn-ink);
  margin-bottom: 8px;
}

.tl-off .tl-head {
  color: var(--blue);
}

.tl-msg {
  font-size: 13px;
  line-height: 1.9;
  color: var(--warn-ink);
}

.tl-off .tl-msg {
  color: var(--ink);
}

.tl-changed {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.tl-src {
  font-size: 11px;
  color: var(--muted);
  margin-top: 10px;
  line-height: 1.7;
}

.verdict-card {
  padding: 0;
  overflow: hidden;
}

.v-head {
  color: #ffffff;
  padding: 14px 20px;
}

.v-red {
  background: var(--warn);
}

.v-blue {
  background: var(--blue);
}

.v-label {
  font-size: 12px;
  opacity: 0.85;
}

.v-title {
  font-size: 22px;
  font-weight: 900;
  margin-top: 2px;
}

.v-sub {
  font-size: 13px;
  margin-top: 2px;
}

.v-body {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.v-hint {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.8;
}
</style>
