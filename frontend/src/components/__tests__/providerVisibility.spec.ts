// @vitest-environment jsdom

// 這次的「問 AI 壞掉」其實不是功能壞掉，是後端啟動時沒載入 .env、默默退回
// 固定假模型，而畫面上完全看不出來——使用者只看到一句「固定模型只確認上下文
// 讀取鏈」，只能解讀成壞了。07 的設計意圖本來就是「demo 絕不能看起來像在用
// 線上模型、實際上卻是固定模型」，所以每則回答都要標明它來自哪個 provider。

import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

Element.prototype.scrollTo = Element.prototype.scrollTo ?? (() => {})

const api = vi.hoisted(() => ({
  createThread: vi.fn<(caseId: string) => Promise<string>>(),
  sendMessage: vi.fn<(params: unknown) => Promise<unknown>>(),
  getRun: vi.fn<(caseId: string, runId: string) => Promise<unknown>>(),
  getRunEvents: vi.fn<(caseId: string, runId: string) => Promise<unknown>>(),
  listMessages: vi.fn<(caseId: string, threadId: string) => Promise<unknown>>(),
  getProposal: vi.fn<(caseId: string, proposalId: string) => Promise<unknown>>(),
}))

vi.mock('@/api/caseapi', async () => {
  const actual = await vi.importActual<typeof import('@/api/caseapi')>('@/api/caseapi')
  return { ...actual, ...api }
})

import ChatSidebar from '@/components/ChatSidebar.vue'

function mockRun(providerConfig: Record<string, string> | undefined) {
  api.createThread.mockResolvedValue('thread_1')
  api.sendMessage.mockResolvedValue({
    message_id: 'msg_1',
    run_id: 'run_1',
    state: 'queued',
    case_revision: 3,
  })
  api.getRun.mockResolvedValue({
    run_id: 'run_1',
    state: 'completed',
    proposal_ids: [],
    ...(providerConfig ? { provider_config: providerConfig } : {}),
  })
  api.getRunEvents.mockResolvedValue([])
  api.listMessages.mockResolvedValue([
    {
      message_id: 'msg_2',
      role: 'assistant',
      content: '選取內容：「訴願人：絕○○○股份有限公司」。',
      intent: null,
      target: null,
      run_id: 'run_1',
    },
  ])
}

async function askSomething() {
  const wrapper = mount(ChatSidebar, {
    props: { caseId: 'case_1', caseRevision: 3 },
    global: { plugins: [ElementPlus] },
  })
  await wrapper.get('input').setValue('訴願期限多久？')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ChatSidebar shows which model actually answered', () => {
  it('warns that a fixed-provider answer is an offline placeholder, not a real AI answer', async () => {
    mockRun({ provider: 'fixed', model: 'deterministic-v1' })

    const wrapper = await askSomething()

    expect(wrapper.text()).toContain('固定模型')
    expect(wrapper.text()).toContain('離線')
  })

  it('labels an online AgentCore answer as the online model instead', async () => {
    mockRun({
      provider: 'agentcore',
      model: 'arn:aws:bedrock-agentcore:us-west-2:1234:runtime/demo',
      region: 'us-west-2',
    })

    const wrapper = await askSomething()

    expect(wrapper.text()).toContain('線上模型')
    expect(wrapper.text()).not.toContain('離線佔位')
  })

  it('does not crash or invent a label when the run carries no provider config', async () => {
    mockRun(undefined)

    const wrapper = await askSomething()

    expect(wrapper.text()).toContain('選取內容')
    expect(wrapper.text()).not.toContain('固定模型')
    expect(wrapper.text()).not.toContain('線上模型')
  })
})
