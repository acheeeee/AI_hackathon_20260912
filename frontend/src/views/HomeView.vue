<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import type { UploadFile } from 'element-plus'
import { ElMessage } from 'element-plus'
import {
  listCases,
  intakeCase,
  CaseApiError,
  type CaseSummary,
} from '@/api/caseapi'
import {
  factFieldLabel,
  PROCESSING_STATUS_LABELS,
  PROCESSING_STATUS_TAG_TYPE,
} from '@/utils/factLabels'

const router = useRouter()

const cases = ref<CaseSummary[]>([])
const loading = ref(true)
const loadError = ref('')

const dialogOpen = ref(false)
const appealFile = ref<File | null>(null)
const appealName = ref('')
const dispositionFile = ref<File | null>(null)
const dispositionName = ref('')
const title = ref('')
const consentToOnlineAnalysis = ref(false)
const submitting = ref(false)
const submitError = ref('')
const extractedPreview = ref<Record<string, string | null> | null>(null)
const analysisNotice = ref<{ type: 'success' | 'warning' | 'info'; message: string } | null>(null)

async function reload() {
  loading.value = true
  loadError.value = ''
  try {
    cases.value = await listCases()
  } catch (err) {
    loadError.value = err instanceof CaseApiError ? err.message : '系統服務目前無法連線'
  } finally {
    loading.value = false
  }
}

onMounted(reload)

function onAppealChange(f: UploadFile) {
  appealFile.value = f.raw ?? null
  appealName.value = f.name
}

function onDispositionChange(f: UploadFile) {
  dispositionFile.value = f.raw ?? null
  dispositionName.value = f.name
}

function resetDialog() {
  appealFile.value = null
  appealName.value = ''
  dispositionFile.value = null
  dispositionName.value = ''
  title.value = ''
  consentToOnlineAnalysis.value = false
  submitError.value = ''
  extractedPreview.value = null
  analysisNotice.value = null
}

function openDialog() {
  resetDialog()
  dialogOpen.value = true
}

async function submit() {
  if (!appealFile.value) return
  submitting.value = true
  submitError.value = ''
  try {
    const result = await intakeCase({
      appealPdf: appealFile.value,
      dispositionPdf: dispositionFile.value ?? undefined,
      title: title.value || undefined,
      consentToOnlineAnalysis: consentToOnlineAnalysis.value,
    })
    extractedPreview.value = result.extracted_fields
    if (result.analysis_status === 'online_completed') {
      analysisNotice.value = {
        type: 'success',
        message: '線上分析已完成；內容仍須人工覆核。',
      }
    } else if (result.analysis_status === 'online_failed_fallback') {
      analysisNotice.value = {
        type: 'warning',
        message: '線上分析未完成，已改用基礎分析；案件與原始檔案已保存。',
      }
    } else {
      analysisNotice.value = {
        type: 'info',
        message: '本次只使用基礎自動分析；內容仍須人工覆核。',
      }
    }
    ElMessage.success('案件已建立，已完成訴願書欄位擷取')
    await reload()
  } catch (err) {
    submitError.value = err instanceof CaseApiError ? err.message : '上傳失敗'
  } finally {
    submitting.value = false
  }
}

function goToCase(caseId: string) {
  router.push({ name: 'case-detail', params: { caseId } })
}

function finishAndOpen() {
  const newest = cases.value[0]
  dialogOpen.value = false
  if (newest) goToCase(newest.case_id)
}

function formatDate(iso: string): string {
  return iso.slice(0, 16).replace('T', ' ')
}
</script>

<template>
  <div class="home">
    <div class="home-head">
      <h1>案件列表</h1>
      <el-button type="primary" @click="openDialog">＋ 上傳新案件</el-button>
    </div>

    <el-alert v-if="loadError" type="error" show-icon :closable="false" class="err">
      {{ loadError }}
    </el-alert>

    <div v-else-if="loading" class="loading">讀取中…</div>

    <div v-else-if="cases.length === 0" class="empty">
      還沒有任何案件，點右上角「上傳新案件」開始。
    </div>

    <div v-else class="case-grid">
      <div
        v-for="item in cases"
        :key="item.case_id"
        class="case-card"
        @click="goToCase(item.case_id)"
      >
        <div class="case-card-top">
          <span class="case-title">{{ item.title || '（未命名案件）' }}</span>
          <el-tag :type="PROCESSING_STATUS_TAG_TYPE[item.processing_status]" size="small">
            {{ PROCESSING_STATUS_LABELS[item.processing_status] }}
          </el-tag>
        </div>
        <div class="case-meta">
          <span v-if="item.official_case_no">{{ item.official_case_no }}</span>
          <span>建立於 {{ formatDate(item.created_at) }}</span>
        </div>
      </div>
    </div>

    <el-dialog v-model="dialogOpen" title="上傳新案件" width="560px" :close-on-click-modal="false">
      <div v-if="!extractedPreview" class="upload-form">
        <el-input v-model="title" placeholder="案件標題（選填，留空則之後可再補）" class="title-input" />

        <div class="doc-slot">
          <div class="slot-head">
            <span class="idx">1</span>
            <span class="slot-name">訴願書</span>
            <span class="req">必要</span>
          </div>
          <div v-if="appealName" class="doc-loaded">
            <span class="doc-name">{{ appealName }}</span>
            <button class="doc-x" @click="appealFile = null; appealName = ''">✕</button>
          </div>
          <el-upload
            v-else
            drag
            accept=".pdf"
            :auto-upload="false"
            :show-file-list="false"
            :on-change="onAppealChange"
            class="slot-drop"
          >
            <div class="drop-hint">拖曳訴願書 PDF，或<em>點擊選擇</em></div>
          </el-upload>
        </div>

        <div class="doc-slot">
          <div class="slot-head">
            <span class="idx">2</span>
            <span class="slot-name">行政處分函</span>
            <span class="opt">選填</span>
          </div>
          <div v-if="dispositionName" class="doc-loaded">
            <span class="doc-name">{{ dispositionName }}</span>
            <button class="doc-x" @click="dispositionFile = null; dispositionName = ''">✕</button>
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
            <div class="drop-hint">拖曳行政處分函 PDF，或<em>點擊選擇</em></div>
          </el-upload>
        </div>

        <p class="hint">
          訴願書格式固定，系統會自動擷取訴願人、原處分機關等欄位；行政處分函格式不固定，原件會保存供查看，未擷取的欄位需要人工補上。
        </p>

        <label class="online-consent">
          <input
            v-model="consentToOnlineAnalysis"
            type="checkbox"
            aria-label="同意將案件文字送至線上分析服務"
          />
          <span>
            我同意將兩份文件各最多 6,000
            字傳送至線上分析服務，產生未經法律覆核的案件分析建議。未勾選時只使用基礎自動分析。
          </span>
        </label>

        <el-alert v-if="submitError" type="error" show-icon :closable="false" class="err">
          {{ submitError }}
        </el-alert>

        <div class="dialog-actions">
          <el-button @click="dialogOpen = false">取消</el-button>
          <el-button
            type="primary"
            :disabled="!appealFile"
            :loading="submitting"
            @click="submit"
          >
            建立案件
          </el-button>
        </div>
      </div>

      <div v-else class="extract-preview">
        <el-alert
          v-if="analysisNotice"
          :type="analysisNotice.type"
          show-icon
          :closable="false"
          class="analysis-notice"
        >
          {{ analysisNotice.message }}
        </el-alert>
        <p class="preview-title">已從訴願書抽出以下欄位：</p>
        <table class="preview-table">
          <tbody>
            <tr v-for="(value, path) in extractedPreview" :key="path">
              <th>{{ factFieldLabel(path) }}</th>
              <td>{{ value ?? '（抽不到，需人工補上）' }}</td>
            </tr>
          </tbody>
        </table>
        <div class="dialog-actions">
          <el-button type="primary" @click="finishAndOpen">開啟案件</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.home {
  max-width: 1080px;
  margin: 0 auto;
  padding: 28px 24px 60px;
}

.home-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.home-head h1 {
  font-size: 22px;
  font-weight: 800;
  color: #0b3d91;
  margin: 0;
}

.err {
  margin-bottom: 16px;
}

.loading,
.empty {
  color: #6b7686;
  padding: 40px 0;
  text-align: center;
}

.case-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
}

.case-card {
  background: #ffffff;
  border: 1px solid #e3e8f0;
  border-radius: 10px;
  padding: 16px;
  cursor: pointer;
  transition: box-shadow 0.15s, transform 0.15s;
}

.case-card:hover {
  box-shadow: 0 6px 18px rgba(11, 61, 145, 0.12);
  transform: translateY(-1px);
}

.case-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.case-title {
  font-weight: 700;
  color: #16233f;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.case-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #7a8699;
}

.upload-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.title-input {
  margin-bottom: 4px;
}

.doc-slot {
  border: 1px dashed #c7d3e8;
  border-radius: 8px;
  padding: 10px 12px;
}

.slot-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 700;
  color: #16233f;
}

.idx {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #0b3d91;
  color: #fff;
  font-size: 11px;
}

.req {
  color: #c0392b;
  font-size: 11px;
  font-weight: 400;
}

.opt {
  color: #7a8699;
  font-size: 11px;
  font-weight: 400;
}

.slot-drop :deep(.el-upload),
.slot-drop :deep(.el-upload-dragger) {
  width: 100%;
  padding: 14px;
}

.drop-hint {
  font-size: 12px;
  color: #8592a6;
}

.drop-hint em {
  color: #0b3d91;
  font-style: normal;
}

.doc-loaded {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #f3f6fc;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 13px;
}

.doc-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-x {
  border: none;
  background: none;
  color: #9aa6ba;
  cursor: pointer;
  font-size: 14px;
}

.hint {
  font-size: 12px;
  color: #7a8699;
  line-height: 1.6;
  margin: 0;
}

.online-consent {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid #d7dfed;
  border-radius: 8px;
  background: #f7f9fc;
  color: #4d5b70;
  font-size: 12px;
  line-height: 1.55;
}

.online-consent input {
  margin-top: 3px;
}

.analysis-notice {
  margin-bottom: 14px;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.preview-title {
  font-weight: 700;
  color: #16233f;
  margin: 0 0 10px;
}

.preview-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  margin-bottom: 16px;
}

.preview-table th {
  text-align: left;
  color: #7a8699;
  font-weight: 500;
  padding: 6px 10px 6px 0;
  white-space: nowrap;
  vertical-align: top;
}

.preview-table td {
  padding: 6px 0;
  color: #16233f;
}
</style>
