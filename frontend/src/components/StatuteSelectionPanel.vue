<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  searchStatutes,
  getStatuteSelection,
  saveStatuteSelection,
  CaseApiError,
  type StatuteHit,
  type SelectedStatute,
} from '@/api/caseapi'

const props = defineProps<{ caseId: string; caseRevision: number }>()
const emit = defineEmits<{ (e: 'selection-saved'): void }>()

const queryInput = ref('')
const hits = ref<StatuteHit[]>([])
const selected = ref<SelectedStatute[]>([])
const expandedChunkIds = ref<Set<string>>(new Set())
const loading = ref(true)
const searching = ref(false)
const saving = ref(false)
const loadError = ref('')

const selectedChunkIds = computed(() => new Set(selected.value.map((item) => item.chunk_id)))

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [selection, search] = await Promise.all([
      getStatuteSelection(props.caseId),
      searchStatutes(props.caseId),
    ])
    selected.value = selection
    hits.value = search.hits
    queryInput.value = search.suggested_query ?? ''
    expandedChunkIds.value = new Set()
  } catch (err) {
    loadError.value = err instanceof CaseApiError ? err.message : '無法讀取選法規資料'
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.caseId, load)

async function runSearch() {
  searching.value = true
  try {
    const search = await searchStatutes(props.caseId, queryInput.value || undefined)
    hits.value = search.hits
    expandedChunkIds.value = new Set()
  } catch (err) {
    ElMessage.error(err instanceof CaseApiError ? err.message : '搜尋失敗')
  } finally {
    searching.value = false
  }
}

function addHit(hit: StatuteHit) {
  if (selectedChunkIds.value.has(hit.chunk_id)) return
  selected.value = [
    ...selected.value,
    {
      chunk_id: hit.chunk_id,
      document_id: hit.document_id,
      section_id: hit.section_id,
      statute_name: hit.statute_name ?? '（未知法規）',
      article_key: hit.article_key ?? '',
      excerpt: hit.excerpt,
    },
  ]
}

function removeSelected(chunkId: string) {
  selected.value = selected.value.filter((item) => item.chunk_id !== chunkId)
}

function toggleFullText(chunkId: string) {
  const next = new Set(expandedChunkIds.value)
  if (next.has(chunkId)) next.delete(chunkId)
  else next.add(chunkId)
  expandedChunkIds.value = next
}

async function save() {
  saving.value = true
  try {
    const result = await saveStatuteSelection({
      caseId: props.caseId,
      expectedCaseRevision: props.caseRevision,
      reason: '人工挑選相關法規',
      selected: selected.value,
    })
    selected.value = result.selected
    emit('selection-saved')
    ElMessage.success('已儲存選定的法規')
  } catch (err) {
    ElMessage.error(err instanceof CaseApiError ? err.message : '儲存失敗')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="panel statute-panel">
    <h2>選法規</h2>

    <el-alert v-if="loadError" type="error" show-icon :closable="false">
      {{ loadError }}
    </el-alert>
    <div v-else-if="loading" class="loading">搜尋中…</div>

    <template v-else>
      <p class="query-hint">請用簡短關鍵字查詢，例如法規名稱、管制行為與核心爭點。</p>

      <div class="search-row">
        <el-input v-model="queryInput" placeholder="輸入關鍵字搜尋 r3 法規語料" size="small" />
        <el-button size="small" type="primary" :loading="searching" @click="runSearch">
          搜尋
        </el-button>
      </div>

      <div class="columns">
        <div class="column">
          <p class="column-title">搜尋結果</p>
          <ul v-if="hits.length" class="hit-list">
            <li v-for="hit in hits" :key="hit.chunk_id" class="hit-item">
              <div class="hit-head">
                <a
                  v-if="hit.official_url"
                  class="hit-name hit-link"
                  :href="hit.official_url"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {{ hit.statute_name }}第{{ hit.article_key }}條
                </a>
                <span v-else class="hit-name">{{ hit.statute_name }}第{{ hit.article_key }}條</span>
                <el-button
                  size="small"
                  :disabled="selectedChunkIds.has(hit.chunk_id)"
                  @click="addHit(hit)"
                >
                  {{ selectedChunkIds.has(hit.chunk_id) ? '已加入' : '加入' }}
                </el-button>
              </div>
              <p class="hit-relevance">
                {{ hit.why_relevant || '尚未產生相關性說明，請承辦人開啟法條後判斷。' }}
              </p>
              <button
                v-if="hit.full_text || hit.excerpt"
                type="button"
                class="full-text-toggle"
                @click="toggleFullText(hit.chunk_id)"
              >
                {{ expandedChunkIds.has(hit.chunk_id) ? '收合完整法條' : '查看完整法條' }}
              </button>
              <p v-if="expandedChunkIds.has(hit.chunk_id)" class="hit-full-text">
                {{ hit.full_text || hit.excerpt }}
              </p>
            </li>
          </ul>
          <p v-else class="empty-hint">沒有搜尋結果。</p>
        </div>

        <div class="column">
          <p class="column-title">已選定（{{ selected.length }}）</p>
          <ul v-if="selected.length" class="hit-list">
            <li v-for="item in selected" :key="item.chunk_id" class="hit-item">
              <div class="hit-head">
                <span class="hit-name">{{ item.statute_name }}第{{ item.article_key }}條</span>
                <el-button size="small" @click="removeSelected(item.chunk_id)">移除</el-button>
              </div>
              <p class="selected-note">已選入草稿法規依據；完整條文請由左側搜尋結果開啟核對。</p>
            </li>
          </ul>
          <p v-else class="empty-hint">還沒選任何法規。</p>
        </div>
      </div>

      <div class="actions">
        <el-button type="primary" :loading="saving" @click="save">儲存選定的法規</el-button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.statute-panel {
  margin-top: 18px;
  background: #ffffff;
  border: 1px solid #e3e8f0;
  border-radius: 10px;
  padding: 16px;
}

.statute-panel h2 {
  font-size: 14px;
  font-weight: 700;
  color: #16233f;
  margin: 0 0 12px;
}

.loading {
  color: #6b7686;
  font-size: 13px;
}

.query-hint {
  font-size: 12px;
  color: #7a8699;
  margin: 0 0 8px;
}

.search-row {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
}

.columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 14px;
}

.column-title {
  font-size: 12px;
  font-weight: 700;
  color: #16233f;
  margin: 0 0 8px;
}

.hit-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 320px;
  overflow-y: auto;
}

.hit-item {
  background: #f7f9fc;
  border: 1px solid #eef1f6;
  border-radius: 8px;
  padding: 8px 10px;
}

.hit-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}

.hit-name {
  font-size: 13px;
  font-weight: 700;
  color: #0b3d91;
}

.hit-link {
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
}

.hit-relevance,
.selected-note,
.hit-full-text {
  font-size: 12px;
  color: #4a5568;
  line-height: 1.6;
  margin: 0;
}

.hit-relevance::before {
  content: '為何相關：';
  font-weight: 700;
  color: #16233f;
}

.selected-note {
  color: #7a8699;
}

.full-text-toggle {
  border: none;
  background: none;
  color: #0b3d91;
  cursor: pointer;
  font-size: 12px;
  padding: 6px 0 0;
}

.hit-full-text {
  white-space: pre-wrap;
  margin-top: 8px;
  padding: 10px;
  background: #ffffff;
  border-left: 3px solid #c7d3e8;
}

.empty-hint {
  color: #9aa6ba;
  font-size: 12px;
}

.actions {
  display: flex;
  justify-content: flex-end;
}
</style>
