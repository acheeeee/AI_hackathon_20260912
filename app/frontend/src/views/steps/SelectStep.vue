<script setup lang="ts">
import { computed } from 'vue'
import { useCaseStore } from '@/stores/case'
import { referenceUrl, decisionUrl } from '@/api/client'
import type { StatuteRecommendation, SimilarCase } from '@/types/appeal'

const caseStore = useCaseStore()

const result = computed(() => caseStore.result)
const appeal = computed(() => result.value?.appeal ?? null)
const timeliness = computed(() => result.value?.timeliness ?? null)

const distributionRows = computed(() => {
  const d = result.value?.distribution
  if (!d) return []
  return Object.entries(d.distribution).map(([label, e]) => ({
    label,
    count: e.count,
    pct: Math.round(e.ratio * 100),
  }))
})

const distributionTotal = computed(() => result.value?.distribution?.total ?? 0)

function refKind(r: StatuteRecommendation): string {
  return r.source === 'interpretation' ? '行政函釋' : '司法判解'
}

function pct(score: number): string {
  return score.toFixed(3)
}

function similarPct(c: SimilarCase): string {
  return c.similarity.toFixed(2)
}

function resultTone(res: string | null): string {
  if (!res) return 'pill-muted'
  if (res.includes('駁回')) return 'pill-warn'
  if (res.includes('撤銷') || res.includes('另處')) return 'pill-ok'
  return 'pill-blue'
}

function toDraft() {
  caseStore.goTo('draft')
}

function backToGate() {
  caseStore.goTo('gate')
}
</script>

<template>
  <div v-if="result" class="page grid">
    <aside class="left">
      <div class="card">
        <div class="card-title">本件</div>
        <div class="meta">
          <div class="m-row"><span class="m-k">訴願人</span><span>{{ appeal?.appellant || '—' }}</span></div>
          <div class="m-row">
            <span class="m-k">原處分機關</span><span>{{ appeal?.original_authority || '—' }}</span>
          </div>
          <div class="m-row"><span class="m-k">案件類型</span><span>{{ appeal?.case_type || '—' }}</span></div>
          <div class="m-row"><span class="m-k">主張</span><span>{{ appeal?.claims || '—' }}</span></div>
        </div>
      </div>

      <div class="card selected">
        <div class="sel-title">已勾選的依據</div>
        <p class="sel-sub">草稿只會引用這裡的東西。沒勾的一律不寫進去。</p>
        <div class="sel-rows">
          <div class="sel-row"><span>法條</span><span class="sel-n">{{ caseStore.selectedCounts.statutes }}</span></div>
          <div class="sel-row"><span>函釋／判解</span><span class="sel-n">{{ caseStore.selectedCounts.refs }}</span></div>
          <div class="sel-row"><span>歷史前例</span><span class="sel-n">{{ caseStore.selectedCounts.similar }}</span></div>
        </div>
        <button class="btn btn-primary btn-block" @click="toDraft">產生決定書草稿</button>
        <p class="sel-note">理由欄依三段論組織：大前提（勾選法條）→ 小前提（擷取事實）→ 結論</p>
        <button class="link-back" @click="backToGate">上一步：程序審查</button>
      </div>

      <div class="note note-amber">
        推薦分數只表示「檢索認為相關」，不表示「法律上應適用」。哪一條該引，由你決定。
      </div>
    </aside>

    <section class="right">
      <div v-if="timeliness?.triggered" class="note note-red big">
        <div class="tl-h">
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M10.3 3.6 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0z" />
            <path d="M12 9v4" /><path d="M12 17h.01" />
          </svg>
          從新從輕　行政罰法第 5 條
        </div>
        {{ timeliness.message }}
      </div>

      <div class="card">
        <div class="hd">
          <span>法條推薦</span>
          <span class="hd-sub">混合檢索　·　BM25 關鍵字 ＋ 向量語意，分數為兩者加權</span>
        </div>
        <div class="items">
          <div
            v-for="s in result.statutes"
            :key="`${s.source}:${s.doc_id}`"
            class="item"
            :class="{ on: caseStore.isStatuteOn(s), disabled: !caseStore.statuteSelectable(s) }"
          >
            <button
              type="button"
              class="cb"
              :class="{ cbon: caseStore.isStatuteOn(s) }"
              :disabled="!caseStore.statuteSelectable(s)"
              @click="caseStore.toggleStatute(s)"
              :aria-label="`勾選 ${s.statute_name} ${s.article_no}`"
            >
              <svg v-if="caseStore.isStatuteOn(s)" width="12" height="12" viewBox="0 0 24 24"
                fill="none" stroke="#fff" stroke-width="3.4" stroke-linecap="round"
                stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
            </button>
            <div class="i-body">
              <div class="i-name">
                {{ s.statute_name }}　{{ s.article_no }}
                <span v-if="s.amend_date" class="pill pill-amber">修正 {{ s.amend_date }}</span>
              </div>
              <div v-if="caseStore.statuteSelectable(s)" class="i-text">{{ s.content }}</div>
              <div v-else class="i-text warn-text">
                <strong>知識庫缺原文，不可勾選。</strong>索引有條號但內容欄為空，無法附原文出處。依零幻覺原則寧可留白。
              </div>
            </div>
            <div class="sc">{{ caseStore.statuteSelectable(s) ? pct(s.score) : '—' }}</div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="hd">
          <span>函釋與判解</span>
          <span class="hd-sub">點標題開新視窗看完整原文</span>
        </div>
        <div class="items">
          <div
            v-for="r in result.refs"
            :key="`${r.source}:${r.doc_id}`"
            class="item"
            :class="{ on: caseStore.isRefOn(r) }"
          >
            <button
              type="button"
              class="cb"
              :class="{ cbon: caseStore.isRefOn(r) }"
              @click="caseStore.toggleRef(r)"
              :aria-label="`勾選 ${r.doc_id}`"
            >
              <svg v-if="caseStore.isRefOn(r)" width="12" height="12" viewBox="0 0 24 24" fill="none"
                stroke="#fff" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round">
                <path d="M20 6 9 17l-5-5" /></svg>
            </button>
            <div class="i-body">
              <div class="i-name">
                <a :href="referenceUrl(r.doc_id)" target="_blank" rel="noopener">{{ r.doc_id }}</a>
                <span class="pill pill-blue">{{ refKind(r) }}</span>
              </div>
              <div class="i-text">{{ r.content }}</div>
            </div>
            <div class="sc">{{ pct(r.score) }}</div>
          </div>
          <p v-if="!result.refs.length" class="empty">（無相關函釋／判解）</p>
        </div>
      </div>

      <div class="card">
        <div class="hd">
          <span>歷史相似前例</span>
          <span class="hd-sub">先用案件類型硬過濾，桶內才比語意</span>
        </div>

        <div class="dist">
          <div v-for="d in distributionRows" :key="d.label" class="dist-cell">
            <div class="dist-pct">{{ d.pct }}%</div>
            <div class="dist-label">{{ d.label }}　{{ d.count }} 件</div>
          </div>
          <div class="dist-total">共 {{ distributionTotal }} 件　·　樣本為均衡抽樣，不代表實際案量分布</div>
        </div>

        <div class="items">
          <div
            v-for="c in result.similar"
            :key="c.doc_id"
            class="item"
            :class="{ on: caseStore.isSimilarOn(c) }"
          >
            <button
              type="button"
              class="cb"
              :class="{ cbon: caseStore.isSimilarOn(c) }"
              @click="caseStore.toggleSimilar(c)"
              :aria-label="`勾選前例 ${c.doc_id}`"
            >
              <svg v-if="caseStore.isSimilarOn(c)" width="12" height="12" viewBox="0 0 24 24"
                fill="none" stroke="#fff" stroke-width="3.4" stroke-linecap="round"
                stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
            </button>
            <div class="i-body">
              <div class="sim-head">
                <a :href="decisionUrl(c.doc_id)" target="_blank" rel="noopener" class="i-name">
                  {{ c.year ? `${c.year} 年　` : '' }}{{ c.case_type || '案件' }}
                </a>
                <span class="pill" :class="resultTone(c.result)">{{ c.result || '—' }}</span>
              </div>
              <div class="i-text">{{ c.summary || '（無摘要）' }}</div>
              <div v-if="c.shared_statutes?.length" class="shared">
                <span v-for="st in c.shared_statutes" :key="st" class="pill pill-ok">共同：{{ st }}</span>
              </div>
            </div>
            <div class="sc">{{ similarPct(c) }}</div>
          </div>
          <p v-if="!result.similar.length" class="empty">（無相似前例）</p>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 20px;
  align-items: start;
}

.left,
.right {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.meta {
  display: flex;
  flex-direction: column;
  gap: 9px;
  font-size: 13px;
}

.m-row {
  display: flex;
  gap: 10px;
}

.m-k {
  color: var(--muted);
  width: 74px;
  flex: none;
}

.selected {
  border-top: 3px solid var(--yellow);
}

.sel-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--blue);
  margin-bottom: 4px;
}

.sel-sub {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 14px;
}

.sel-rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.sel-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--tint);
  border-radius: var(--radius-sm);
  padding: 9px 12px;
  font-size: 13px;
  font-weight: 700;
  color: var(--blue);
}

.sel-n {
  font-weight: 900;
}

.sel-note {
  font-size: 11px;
  color: var(--muted);
  text-align: center;
  margin-top: 9px;
  line-height: 1.7;
}

.link-back {
  border: none;
  background: transparent;
  font-family: inherit;
  font-size: 11px;
  color: var(--muted);
  cursor: pointer;
  margin-top: 8px;
  width: 100%;
}

.big {
  border-left-width: 4px;
  font-size: 13px;
  line-height: 1.9;
}

.tl-h {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 15px;
  font-weight: 700;
  margin-bottom: 7px;
}

.hd {
  font-size: 16px;
  font-weight: 700;
  color: var(--blue);
  padding-bottom: 10px;
  border-bottom: 2px solid var(--line);
  margin-bottom: 14px;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.hd-sub {
  font-size: 12px;
  color: var(--muted);
  font-weight: 400;
}

.items {
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.item {
  display: grid;
  grid-template-columns: 20px 1fr 62px;
  gap: 13px;
  padding: 13px 15px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: #ffffff;
  align-items: start;
}

.item.on {
  border-color: var(--blue);
  background: var(--tint);
}

.item.disabled {
  background: var(--amber-bg);
  border-color: var(--yellow);
}

.cb {
  width: 18px;
  height: 18px;
  border-radius: 5px;
  border: 1.5px solid var(--line-strong);
  background: #ffffff;
  margin-top: 2px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
}

.cb:disabled {
  cursor: not-allowed;
  border-color: var(--yellow);
}

.cb.cbon {
  background: var(--blue);
  border-color: var(--blue);
}

.i-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--blue);
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.i-text {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.8;
  margin-top: 4px;
}

.warn-text {
  color: var(--amber-ink);
}

.sc {
  font-size: 12px;
  font-weight: 700;
  color: var(--blue-light);
  text-align: right;
}

.shared {
  margin-top: 7px;
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.sim-head {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
}

.dist {
  display: flex;
  gap: 9px;
  margin-bottom: 14px;
  flex-wrap: wrap;
  align-items: center;
}

.dist-cell {
  background: var(--bg);
  border-radius: var(--radius-sm);
  padding: 9px 16px;
  text-align: center;
  min-width: 92px;
}

.dist-pct {
  font-size: 20px;
  font-weight: 900;
  color: var(--blue);
}

.dist-label {
  font-size: 12px;
  color: var(--muted);
}

.dist-total {
  font-size: 12px;
  color: var(--muted);
}

.empty {
  font-size: 13px;
  color: var(--muted);
}

@media (max-width: 1000px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
