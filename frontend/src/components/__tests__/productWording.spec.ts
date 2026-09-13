// @vitest-environment node

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const SOURCE_ROOT = fileURLToPath(new URL('../../', import.meta.url))

const PRODUCT_SURFACES = [
  'App.vue',
  'components/AppHeader.vue',
  'components/ChatSidebar.vue',
  'components/ProceduralReviewPanel.vue',
  'utils/factLabels.ts',
  'views/CaseDetailView.vue',
  'views/HomeView.vue',
  'views/steps/DraftStep.vue',
  'views/steps/ExtractStep.vue',
  'views/steps/GateStep.vue',
  'views/steps/SelectStep.vue',
  'views/steps/UploadStep.vue',
]

const EXPOSED_ENGINEERING_PHRASES = [
  'AgentCore 線上模型',
  'Gemini 已連線',
  '未設定 API key',
  '固定 Mock 產生',
  '固定模型（離線佔位',
  'LLM 生成',
  'LLM 模式',
  'Mock 規則',
  '目前示範環境',
  '載入示範案例',
  '使用 LLM 補強',
  '耗用 Gemini 額度',
  'BM25 關鍵字',
  '程序審查引擎（src/gate.py）尚未實作',
  '無法連線到後端',
  '本機分析',
  '本機自動分析',
  'verify／explain',
  '後端 intake',
  '先用案件類型硬過濾',
  '樣本為均衡抽樣',
  '目前採單一文本解析',
]

describe('user-facing product wording', () => {
  it.each(PRODUCT_SURFACES)('%s does not expose implementation or showcase wording', (path) => {
    const source = readFileSync(`${SOURCE_ROOT}/${path}`, 'utf8')

    for (const phrase of EXPOSED_ENGINEERING_PHRASES) {
      expect(source, `${path} still contains ${phrase}`).not.toContain(phrase)
    }
  })
})
