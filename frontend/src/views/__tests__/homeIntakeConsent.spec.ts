// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  listCases: vi.fn<() => Promise<unknown[]>>(),
  intakeCase: vi.fn<(params: unknown) => Promise<unknown>>(),
}))

vi.mock('@/api/caseapi', async () => {
  const actual = await vi.importActual<typeof import('@/api/caseapi')>('@/api/caseapi')
  return { ...actual, ...api }
})

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn<(target: unknown) => void>() }),
}))

import HomeView from '@/views/HomeView.vue'

describe('new-case upload consent', () => {
  it('shows an explicit online-analysis consent control that starts unchecked', async () => {
    api.listCases.mockResolvedValue([])
    const wrapper = mount(HomeView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    await wrapper.get('.home-head button').trigger('click')

    const consent = wrapper.get(
      'input[type="checkbox"][aria-label="同意將案件文字送至線上分析服務"]',
    )
    expect((consent.element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.text()).toContain('未勾選時只使用基礎自動分析')
    expect(wrapper.text()).not.toMatch(/AWS|Bedrock|AgentCore|fixed|mock|demo/i)
  })

  it('shows a safe fallback status when online analysis fails after upload', async () => {
    api.listCases.mockResolvedValue([])
    api.intakeCase.mockResolvedValue({
      case_id: 'case_1',
      case_revision: 1,
      extracted_fields: {},
      analysis_status: 'online_failed_fallback',
      analysis_error: 'private infrastructure detail',
    })
    const wrapper = mount(HomeView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    await wrapper.get('.home-head button').trigger('click')

    const fileInput = wrapper.get('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', {
      configurable: true,
      value: [new File(['%PDF-1.4'], 'appeal.pdf', { type: 'application/pdf' })],
    })
    await fileInput.trigger('change')
    await wrapper
      .get('input[aria-label="同意將案件文字送至線上分析服務"]')
      .setValue(true)
    await wrapper
      .findAll('.dialog-actions button')
      .find((button) => button.text().trim() === '建立案件')!
      .trigger('click')
    await flushPromises()

    expect(api.intakeCase).toHaveBeenCalledWith(
      expect.objectContaining({ consentToOnlineAnalysis: true }),
    )
    expect(wrapper.text()).toContain('線上分析未完成，已改用基礎分析；案件與原始檔案已保存。')
    expect(wrapper.text()).not.toContain('private infrastructure detail')
  })
})
