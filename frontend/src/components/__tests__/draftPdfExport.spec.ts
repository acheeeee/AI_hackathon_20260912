// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getDraftResource: vi.fn<(caseId: string, draftId: string) => Promise<unknown>>(),
  patchDraftBlock: vi.fn<(params: unknown) => Promise<unknown>>(),
  downloadDraftPdf: vi.fn<(params: unknown) => Promise<void>>(),
}))

vi.mock('@/api/caseapi', () => ({
  ...api,
  CaseApiError: class CaseApiError extends Error {},
}))

import DraftEditorPanel from '@/components/DraftEditorPanel.vue'

describe('draft PDF export journey', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getDraftResource.mockResolvedValue({
      resource_id: 'draft_1',
      resource_kind: 'draft',
      resource_revision: 'res_2',
      parent_revision: 'res_1',
      origin: 'merged',
      content: {
        draft_kind: 'appeal_decision',
        title: '訴願決定書草稿',
        blocks: [
          {
            block_id: 'main-1',
            text: '主文\n（待承辦人核定處理結果後填寫）',
            citations: [],
          },
        ],
      },
      content_hash: 'content_hash',
      dependencies: {},
      is_head: true,
      freshness: 'current',
      created_by: 'user',
      created_at: '2026-09-13T00:00:00Z',
    })
    api.downloadDraftPdf.mockResolvedValue()
  })

  function mountEditor() {
    return mount(DraftEditorPanel, {
      props: {
        caseId: 'case_1',
        caseRevision: 3,
        draftId: 'draft_1',
        draftHead: { revision_id: 'res_2', kind: 'draft', freshness: 'current' },
      },
      global: { plugins: [ElementPlus] },
    })
  }

  it('downloads the persisted draft head from the 草稿正文 panel', async () => {
    const wrapper = mountEditor()
    await flushPromises()

    const downloadButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('下載 PDF'))
    expect(downloadButton).toBeDefined()
    await downloadButton!.trigger('click')
    await flushPromises()

    expect(api.downloadDraftPdf).toHaveBeenCalledWith({
      caseId: 'case_1',
      draftId: 'draft_1',
    })
  })

  it('does not export unsaved textarea edits', async () => {
    const wrapper = mountEditor()
    await flushPromises()

    await wrapper.get('textarea').setValue('尚未儲存的修改')
    const downloadButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('下載 PDF'))

    expect(downloadButton!.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('請先儲存修改再下載')
    expect(api.downloadDraftPdf).not.toHaveBeenCalled()
  })

  it('shows a visible error when PDF generation fails', async () => {
    api.downloadDraftPdf.mockRejectedValue(new Error('export failed'))
    const errorMessage = vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
    const wrapper = mountEditor()
    await flushPromises()

    const downloadButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('下載 PDF'))
    await downloadButton!.trigger('click')
    await flushPromises()

    expect(errorMessage).toHaveBeenCalledWith('下載 PDF 失敗')
  })
})
