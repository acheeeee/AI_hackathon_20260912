<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getCase,
  getFacts,
  listDocuments,
  documentContentUrl,
  CaseApiError,
  type CaseDetail,
  type FactFieldValue,
  type CaseDocument,
  type FactFieldTarget,
} from '@/api/caseapi'
import {
  factFieldLabel,
  factOriginLabel,
  PROCESSING_STATUS_LABELS,
  PROCESSING_STATUS_TAG_TYPE,
} from '@/utils/factLabels'
import ChatSidebar from '@/components/ChatSidebar.vue'
import ProceduralReviewPanel from '@/components/ProceduralReviewPanel.vue'
import StatuteSelectionPanel from '@/components/StatuteSelectionPanel.vue'
import DraftGenerationPanel from '@/components/DraftGenerationPanel.vue'

const route = useRoute()
const router = useRouter()
const caseId = computed(() => route.params.caseId as string)

const detail = ref<CaseDetail | null>(null)
const facts = ref<Record<string, FactFieldValue>>({})
const documents = ref<CaseDocument[]>([])
const activeDocumentId = ref<string | null>(null)
const loading = ref(true)
const loadError = ref('')
const sidebar = ref<InstanceType<typeof ChatSidebar> | null>(null)

const factsRevisionId = computed(() => detail.value?.active_heads.facts?.revision_id ?? null)

function askAboutField(path: string) {
  const revisionId = factsRevisionId.value
  if (!revisionId) return
  const target: FactFieldTarget = {
    kind: 'fact_field',
    resource_id: 'facts',
    resource_revision: revisionId,
    field_path: path,
  }
  sidebar.value?.askAboutField(factFieldLabel(path), target)
}

const documentRoleLabel: Record<string, string> = {
  appeal: '訴願書',
  disposition: '行政處分函',
}

const activeDocument = computed(
  () => documents.value.find((d) => d.document_id === activeDocumentId.value) ?? null,
)

// 子面板發事件回來時不要再掀起整頁 spinner：那會把 v-else-if="detail" 整段
// 換成 loading 區塊，子元件被卸載重建，剛生成好的草稿結果就消失了。
async function load(showSpinner = true) {
  loading.value = showSpinner
  loadError.value = ''
  try {
    const [d, f, docs] = await Promise.all([
      getCase(caseId.value),
      getFacts(caseId.value),
      listDocuments(caseId.value),
    ])
    detail.value = d
    facts.value = f
    documents.value = docs
    activeDocumentId.value = docs[0]?.document_id ?? null
  } catch (err) {
    loadError.value = err instanceof CaseApiError ? err.message : '無法讀取案件'
  } finally {
    loading.value = false
  }
}

function refresh() {
  return load(false)
}

onMounted(() => load())
watch(caseId, () => load())

function backToList() {
  router.push({ name: 'home' })
}
</script>

<template>
  <div class="case-detail">
    <button class="back" @click="backToList">← 回案件列表</button>

    <el-alert v-if="loadError" type="error" show-icon :closable="false">
      {{ loadError }}
    </el-alert>

    <div v-else-if="loading" class="loading">讀取中…</div>

    <template v-else-if="detail">
      <div class="head">
        <h1>{{ detail.title || '（未命名案件）' }}</h1>
        <el-tag :type="PROCESSING_STATUS_TAG_TYPE[detail.processing_status]">
          {{ PROCESSING_STATUS_LABELS[detail.processing_status] }}
        </el-tag>
      </div>
      <p class="case-sub">
        {{ detail.official_case_no || '尚未有正式案號' }}　·　案件版本 {{ detail.case_revision }}
      </p>

      <div class="layout">
        <div class="panel facts-panel">
          <h2>抽取事實（可再修改）</h2>
          <table v-if="Object.keys(facts).length" class="facts-table">
            <tbody>
              <tr v-for="(field, path) in facts" :key="path">
                <th>{{ factFieldLabel(path) }}</th>
                <td>
                  <span>{{ field.value ?? '（未填）' }}</span>
                  <el-tag size="small" class="origin-tag" effect="plain">
                    {{ factOriginLabel(field.origin) }}
                  </el-tag>
                  <button class="ask-ai" @click="askAboutField(path)">問 AI</button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="empty-hint">尚未抽取到任何事實欄位，請人工補上。</p>
        </div>

        <div class="panel doc-panel">
          <h2>原始文件</h2>
          <div v-if="documents.length" class="doc-tabs">
            <button
              v-for="doc in documents"
              :key="doc.document_id"
              class="doc-tab"
              :class="{ active: doc.document_id === activeDocumentId }"
              @click="activeDocumentId = doc.document_id"
            >
              {{ documentRoleLabel[doc.document_role] || doc.document_role }}
            </button>
          </div>
          <iframe
            v-if="activeDocument"
            :key="activeDocument.document_id"
            class="doc-frame"
            :src="documentContentUrl(caseId, activeDocument.document_id)"
          />
          <p v-else class="empty-hint">沒有上傳的原始文件。</p>
        </div>
      </div>

      <ProceduralReviewPanel
        :case-id="caseId"
        :case-revision="detail.case_revision"
        @facts-updated="refresh"
      />

      <StatuteSelectionPanel
        :case-id="caseId"
        :case-revision="detail.case_revision"
        @selection-saved="refresh"
      />

      <DraftGenerationPanel
        :case-id="caseId"
        :case-revision="detail.case_revision"
        @draft-generated="refresh"
      />

      <ChatSidebar ref="sidebar" :case-id="caseId" :case-revision="detail.case_revision" />
    </template>
  </div>
</template>

<style scoped>
.case-detail {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px 24px 60px;
}

.back {
  border: none;
  background: none;
  color: #0b3d91;
  cursor: pointer;
  font-size: 13px;
  padding: 0;
  margin-bottom: 14px;
}

.loading {
  color: #6b7686;
  padding: 40px 0;
  text-align: center;
}

.head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.head h1 {
  font-size: 20px;
  font-weight: 800;
  color: #0b3d91;
  margin: 0;
}

.case-sub {
  font-size: 12px;
  color: #7a8699;
  margin: 4px 0 20px;
}

.layout {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: 18px;
  align-items: start;
}

.panel {
  background: #ffffff;
  border: 1px solid #e3e8f0;
  border-radius: 10px;
  padding: 16px;
}

.panel h2 {
  font-size: 14px;
  font-weight: 700;
  color: #16233f;
  margin: 0 0 12px;
}

.facts-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.facts-table th {
  text-align: left;
  color: #7a8699;
  font-weight: 500;
  padding: 8px 10px 8px 0;
  white-space: nowrap;
  vertical-align: top;
}

.facts-table td {
  padding: 8px 0;
  color: #16233f;
}

.origin-tag {
  margin-left: 8px;
}

.ask-ai {
  margin-left: 8px;
  border: 1px solid #c7d3e8;
  background: #f7f9fc;
  color: #0b3d91;
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
}

.empty-hint {
  color: #9aa6ba;
  font-size: 13px;
}

.doc-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}

.doc-tab {
  border: 1px solid #d6deed;
  background: #f7f9fc;
  color: #4a5568;
  border-radius: 6px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
}

.doc-tab.active {
  background: #0b3d91;
  border-color: #0b3d91;
  color: #fff;
}

.doc-frame {
  width: 100%;
  height: 720px;
  border: 1px solid #e3e8f0;
  border-radius: 6px;
}
</style>
