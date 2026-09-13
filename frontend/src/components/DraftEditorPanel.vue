<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  CaseApiError,
  downloadDraftPdf,
  getDraftResource,
  patchDraftBlock,
  type DraftBlockTarget,
  type ProposalBlock,
  type ResourceHead,
} from '@/api/caseapi'
import { buildDraftBlockTarget } from '@/utils/draftSelection'

const props = defineProps<{
  caseId: string
  caseRevision: number
  draftId: string
  draftHead: ResourceHead
}>()
const emit = defineEmits<{
  (e: 'draft-updated'): void
  (e: 'explain-selection', label: string, target: DraftBlockTarget): void
  (e: 'revise-selection', label: string, target: DraftBlockTarget): void
}>()

const MAX_SELECTION_LABEL_LENGTH = 24

interface TextareaHost {
  // Element Plus 的元件 ref（透過 `defineExpose`）在模板存取時已經自動解開
  // 內部的 ShallowRef，所以這裡直接是原生 <textarea>，不是 ref 包裝物件。
  textarea?: HTMLTextAreaElement | null
}

const blockInputs: Record<string, TextareaHost | null> = reactive({})
const selection = ref<{ blockId: string; start: number; end: number } | null>(null)

function setBlockInputRef(blockId: string, el: unknown) {
  blockInputs[blockId] = el as TextareaHost | null
}

function nativeTextarea(blockId: string): HTMLTextAreaElement | null {
  return blockInputs[blockId]?.textarea ?? null
}

function onSelect(blockId: string) {
  const el = nativeTextarea(blockId)
  const start = el?.selectionStart ?? null
  const end = el?.selectionEnd ?? null
  if (start === null || end === null || end <= start) {
    if (selection.value?.blockId === blockId) selection.value = null
    return
  }
  selection.value = { blockId, start, end }
}

function selectionLabel(text: string): string {
  return text.length > MAX_SELECTION_LABEL_LENGTH
    ? `${text.slice(0, MAX_SELECTION_LABEL_LENGTH)}…`
    : text
}

async function buildTarget(block: ProposalBlock): Promise<DraftBlockTarget> {
  const sel = selection.value
  const range =
    sel && sel.blockId === block.block_id
      ? { start: sel.start, end: sel.end }
      : { start: 0, end: block.text.length }
  return buildDraftBlockTarget({
    resourceId: props.draftId,
    resourceRevision: currentResourceRevision.value,
    blockId: block.block_id,
    blockText: block.text,
    utf16Start: range.start,
    utf16End: range.end,
  })
}

async function explainSelected(block: ProposalBlock) {
  if (isDirty(block)) return
  const target = await buildTarget(block)
  emit('explain-selection', selectionLabel(target.selected_text), target)
}

async function reviseSelected(block: ProposalBlock) {
  if (isDirty(block)) return
  const target = await buildTarget(block)
  emit('revise-selection', selectionLabel(target.selected_text), target)
}

const loading = ref(true)
const loadError = ref('')
const blocks = ref<ProposalBlock[]>([])
const savedBlocks = ref<ProposalBlock[]>([])
const title = ref<string | null>(null)
const origin = ref('')
const freshness = ref(props.draftHead.freshness)
const currentCaseRevision = ref(props.caseRevision)
const currentResourceRevision = ref(props.draftHead.revision_id)
const savingBlockId = ref<string | null>(null)
const editingBlockId = ref<string | null>(null)
const downloadingPdf = ref(false)

const originLabel = computed(() => {
  const labels: Record<string, string> = {
    human: '人工版本',
    merged: '合併版本',
    program: '系統空殼',
    ai: 'AI 版本',
  }
  return labels[origin.value] ?? '其他來源'
})

const isPlaceholder = computed(
  () => blocks.value.length === 1 && blocks.value[0]?.text === '（尚未生成內容）',
)

const hasUnsavedChanges = computed(() => blocks.value.some((block) => isDirty(block)))

function isDirty(block: ProposalBlock): boolean {
  const saved = savedBlocks.value.find((item) => item.block_id === block.block_id)
  return saved?.text !== block.text
}

function updateBlockText(blockId: string, text: string) {
  blocks.value = blocks.value.map((block) =>
    block.block_id === blockId ? { ...block, text } : block,
  )
}

function startEditing(blockId: string) {
  if (editingBlockId.value !== null || savingBlockId.value !== null) return
  selection.value = null
  editingBlockId.value = blockId
}

function cancelEditing(block: ProposalBlock) {
  const saved = savedBlocks.value.find((item) => item.block_id === block.block_id)
  if (saved) updateBlockText(block.block_id, saved.text)
  selection.value = null
  editingBlockId.value = null
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const resource = await getDraftResource(props.caseId, props.draftId)
    blocks.value = resource.content.blocks.map((block) => ({ ...block }))
    savedBlocks.value = resource.content.blocks.map((block) => ({ ...block }))
    title.value = resource.content.title
    origin.value = resource.origin
    freshness.value = resource.freshness ?? props.draftHead.freshness
    currentCaseRevision.value = props.caseRevision
    currentResourceRevision.value = resource.resource_revision
    editingBlockId.value = null
    selection.value = null
  } catch (err) {
    loadError.value = err instanceof CaseApiError ? err.message : '無法讀取草稿正文'
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.caseId, props.draftId, props.draftHead.revision_id],
  load,
  { immediate: true },
)

async function saveBlock(block: ProposalBlock) {
  if (!isDirty(block) || savingBlockId.value !== null) return

  savingBlockId.value = block.block_id
  try {
    const result = await patchDraftBlock({
      caseId: props.caseId,
      draftId: props.draftId,
      expectedCaseRevision: currentCaseRevision.value,
      baseResourceRevision: currentResourceRevision.value,
      block,
    })
    blocks.value = result.blocks.map((item) => ({ ...item }))
    savedBlocks.value = result.blocks.map((item) => ({ ...item }))
    currentCaseRevision.value = result.case_revision
    currentResourceRevision.value = result.resource_revision
    freshness.value = result.freshness
    editingBlockId.value = null
    selection.value = null
    ElMessage.success('此段已儲存')
    emit('draft-updated')
  } catch (err) {
    if (
      err instanceof CaseApiError &&
      (err.code === 'REVISION_CONFLICT' || err.code === 'TARGET_MOVED')
    ) {
      ElMessage.warning('草稿已有更新，已重新載入最新版本；請確認後再編輯。')
      await load()
      emit('draft-updated')
    } else {
      ElMessage.error(err instanceof CaseApiError ? err.message : '儲存草稿失敗')
    }
  } finally {
    savingBlockId.value = null
  }
}

async function downloadPdf() {
  if (hasUnsavedChanges.value || downloadingPdf.value) return
  downloadingPdf.value = true
  try {
    await downloadDraftPdf({ caseId: props.caseId, draftId: props.draftId })
    ElMessage.success('PDF 已開始下載')
  } catch (err) {
    ElMessage.error(err instanceof CaseApiError ? err.message : '下載 PDF 失敗')
  } finally {
    downloadingPdf.value = false
  }
}
</script>

<template>
  <section class="panel draft-editor-panel">
    <div class="panel-head">
      <div>
        <h2>生成的草稿內容</h2>
        <p v-if="title" class="draft-title">{{ title }}</p>
      </div>
      <div class="status-tags">
        <el-button
          size="small"
          type="primary"
          plain
          :loading="downloadingPdf"
          :disabled="loading || Boolean(loadError) || isPlaceholder || hasUnsavedChanges"
          @click="downloadPdf"
        >
          下載 PDF
        </el-button>
        <el-tag size="small" effect="plain">{{ originLabel }}</el-tag>
        <el-tag size="small" :type="freshness === 'current' ? 'success' : 'warning'">
          {{ freshness === 'current' ? '目前有效' : '內容待覆核' }}
        </el-tag>
      </div>
    </div>

    <el-alert v-if="loadError" type="error" show-icon :closable="false">
      {{ loadError }}
    </el-alert>
    <p v-else-if="loading" class="empty-hint">讀取草稿中…</p>
    <el-alert v-else-if="isPlaceholder" type="info" show-icon :closable="false">
      草稿提案尚未採用。請先在上方生成面板確認內容並按「採用這份草稿」。
    </el-alert>

    <div v-else class="draft-blocks">
      <article v-for="(block, index) in blocks" :key="block.block_id" class="draft-block">
        <div class="block-head">
          <span>段落 {{ index + 1 }}</span>
        </div>
        <el-input
          v-if="editingBlockId === block.block_id"
          :ref="(el: unknown) => setBlockInputRef(block.block_id, el)"
          :model-value="block.text"
          type="textarea"
          :autosize="{ minRows: 4, maxRows: 14 }"
          @update:model-value="updateBlockText(block.block_id, String($event))"
          @select="onSelect(block.block_id)"
          @mouseup="onSelect(block.block_id)"
          @keyup="onSelect(block.block_id)"
        />
        <p v-else class="draft-block-text">{{ block.text }}</p>
        <p v-if="block.citations.length" class="citations">
          引用：{{ block.citations.join('、') }}
        </p>
        <div class="block-actions">
          <div class="selection-toolbar">
            <button
              type="button"
              class="explain-selection"
              :disabled="isDirty(block)"
              @click="explainSelected(block)"
            >
              請 AI 解釋
            </button>
            <button
              type="button"
              class="revise-selection"
              :disabled="isDirty(block)"
              @click="reviseSelected(block)"
            >
              請 AI 修改此段
            </button>
          </div>
          <div class="edit-actions">
            <span v-if="isDirty(block)" class="unsaved">尚未儲存</span>
            <template v-if="editingBlockId === block.block_id">
              <el-button
                size="small"
                :disabled="savingBlockId !== null"
                @click="cancelEditing(block)"
              >
                取消
              </el-button>
              <el-button
                size="small"
                type="primary"
                :disabled="!isDirty(block) || savingBlockId !== null"
                :loading="savingBlockId === block.block_id"
                @click="saveBlock(block)"
              >
                儲存
              </el-button>
            </template>
            <el-button
              v-else
              size="small"
              type="primary"
              plain
              :disabled="editingBlockId !== null || savingBlockId !== null"
              @click="startEditing(block.block_id)"
            >
              編輯
            </el-button>
          </div>
        </div>
      </article>
    </div>

    <p v-if="!loading && !loadError && !isPlaceholder" class="editing-note">
      人工編輯會建立新的不可變版本；若草稿原本已標示待覆核，文字修改不會自行解除。
    </p>
    <p v-if="hasUnsavedChanges" class="download-warning">請先儲存修改再下載 PDF。</p>
  </section>
</template>

<style scoped>
.draft-editor-panel {
  margin-top: 18px;
  background: #ffffff;
  border: 1px solid #e3e8f0;
  border-radius: 10px;
  padding: 16px;
}

.panel-head,
.block-head,
.block-actions,
.status-tags,
.edit-actions {
  display: flex;
  align-items: center;
}

.panel-head,
.block-head,
.block-actions {
  justify-content: space-between;
}

.panel-head {
  gap: 16px;
  margin-bottom: 12px;
}

.panel-head h2 {
  font-size: 14px;
  font-weight: 700;
  color: #16233f;
  margin: 0;
}

.draft-title,
.editing-note,
.citations {
  color: #7a8699;
  font-size: 12px;
}

.draft-title {
  margin: 4px 0 0;
}

.status-tags {
  gap: 6px;
  flex-shrink: 0;
}

.edit-actions {
  gap: 8px;
}

.draft-blocks {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.selection-toolbar {
  display: flex;
  gap: 8px;
}

.selection-toolbar button {
  border: 1px solid #c7d3e8;
  background: #f7f9fc;
  color: #0b3d91;
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 11px;
  cursor: pointer;
}

.selection-toolbar button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.draft-block {
  background: #f7f9fc;
  border: 1px solid #e3e8f0;
  border-radius: 8px;
  padding: 12px;
}

.block-head {
  color: #16233f;
  font-size: 12px;
  font-weight: 700;
  margin-bottom: 8px;
}

.draft-block-text {
  color: #16233f;
  font-size: 14px;
  line-height: 1.9;
  margin: 0;
  white-space: pre-wrap;
}

.citations {
  margin: 7px 0 0;
}

.block-actions {
  margin-top: 8px;
}

.unsaved {
  color: #b56a00;
  font-size: 12px;
}

.download-warning {
  color: #b56a00;
  font-size: 12px;
  margin: 6px 0 0;
}

.editing-note {
  margin: 12px 0 0;
}

.empty-hint {
  color: #9aa6ba;
  font-size: 13px;
}
</style>
