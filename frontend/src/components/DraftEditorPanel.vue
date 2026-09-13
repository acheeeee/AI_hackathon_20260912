<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  CaseApiError,
  getDraftResource,
  patchDraftBlock,
  type ProposalBlock,
  type ResourceHead,
} from '@/api/caseapi'

const props = defineProps<{
  caseId: string
  caseRevision: number
  draftId: string
  draftHead: ResourceHead
}>()
const emit = defineEmits<{ (e: 'draft-updated'): void }>()

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

function isDirty(block: ProposalBlock): boolean {
  const saved = savedBlocks.value.find((item) => item.block_id === block.block_id)
  return saved?.text !== block.text
}

function updateBlockText(blockId: string, text: string) {
  blocks.value = blocks.value.map((block) =>
    block.block_id === blockId ? { ...block, text } : block,
  )
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
</script>

<template>
  <section class="panel draft-editor-panel">
    <div class="panel-head">
      <div>
        <h2>草稿正文</h2>
        <p v-if="title" class="draft-title">{{ title }}</p>
      </div>
      <div class="status-tags">
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
          <span class="block-id">{{ block.block_id }}</span>
        </div>
        <el-input
          :model-value="block.text"
          type="textarea"
          :autosize="{ minRows: 4, maxRows: 14 }"
          @update:model-value="updateBlockText(block.block_id, String($event))"
        />
        <p v-if="block.citations.length" class="citations">
          引用：{{ block.citations.join('、') }}
        </p>
        <div class="block-actions">
          <span v-if="isDirty(block)" class="unsaved">尚未儲存</span>
          <el-button
            size="small"
            type="primary"
            :disabled="!isDirty(block) || savingBlockId !== null"
            :loading="savingBlockId === block.block_id"
            @click="saveBlock(block)"
          >
            儲存此段
          </el-button>
        </div>
      </article>
    </div>

    <p v-if="!loading && !loadError && !isPlaceholder" class="editing-note">
      人工編輯會建立新的不可變版本；若草稿原本已標示待覆核，文字修改不會自行解除。
    </p>
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
.status-tags {
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

.draft-blocks {
  display: flex;
  flex-direction: column;
  gap: 12px;
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

.block-id {
  color: #9aa6ba;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  font-weight: 400;
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

.editing-note {
  margin: 12px 0 0;
}

.empty-hint {
  color: #9aa6ba;
  font-size: 13px;
}
</style>
