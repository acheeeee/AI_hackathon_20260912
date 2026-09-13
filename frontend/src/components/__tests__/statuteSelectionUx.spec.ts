// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  searchStatutes: vi.fn<(caseId: string, query?: string) => Promise<unknown>>(),
  getStatuteSelection: vi.fn<(caseId: string) => Promise<unknown>>(),
  saveStatuteSelection: vi.fn<(params: unknown) => Promise<unknown>>(),
}))

vi.mock('@/api/caseapi', async () => {
  const actual = await vi.importActual<typeof import('@/api/caseapi')>('@/api/caseapi')
  return { ...actual, ...api }
})

import StatuteSelectionPanel from '@/components/StatuteSelectionPanel.vue'

const BACKGROUND_QUERY =
  '訴願人於114年3月31日申請洗錢防制登記，經補正後，原處分機關仍以申請書件不完備、逾期不能完成補正為由不予登記。'
const SUGGESTED_QUERY = '洗錢防制、虛擬資產服務業、登記申請要件'
const FULL_TEXT =
  '第六條　提供虛擬資產服務之事業或人員未依規定完成洗錢防制登記者，不得提供虛擬資產服務。'
const WHY_RELEVANT = '本案爭點正是虛擬資產服務業者是否具備登記申請要件。'
const OFFICIAL_URL = 'https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=G0380131&flno=6'

function searchResult() {
  return {
    query_used: BACKGROUND_QUERY,
    suggested_query: SUGGESTED_QUERY,
    hits: [
      {
        chunk_id: 'chunk_law_6',
        document_id: 'doc_law',
        section_id: 'sec_law_6',
        statute_name: '洗錢防制法',
        article_key: '6',
        excerpt: FULL_TEXT,
        score: 12.4,
        why_relevant: WHY_RELEVANT,
        full_text: FULL_TEXT,
        official_url: OFFICIAL_URL,
      },
    ],
  }
}

async function mountPanel() {
  api.getStatuteSelection.mockResolvedValue([])
  api.searchStatutes.mockResolvedValue(searchResult())

  const wrapper = mount(StatuteSelectionPanel, {
    props: { caseId: 'case_1', caseRevision: 3 },
    global: { plugins: [ElementPlus] },
  })
  await flushPromises()
  return wrapper
}

describe('StatuteSelectionPanel: human-readable legal search', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('removes the implementation boast and keeps the long automatic query in the background', async () => {
    const wrapper = await mountPanel()

    expect(wrapper.text()).not.toContain('真的 BM25，不是憑空建議')
    expect(wrapper.text()).not.toContain(BACKGROUND_QUERY)
    expect(wrapper.text()).not.toContain('目前查詢字串')
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe(SUGGESTED_QUERY)
  })

  it('shows why each result is relevant instead of printing the statute excerpt as small text', async () => {
    const wrapper = await mountPanel()

    expect(wrapper.text()).toContain(WHY_RELEVANT)
    expect(wrapper.text()).not.toContain(FULL_TEXT)
  })

  it('submits the concise human-facing keywords instead of the background narrative', async () => {
    const wrapper = await mountPanel()

    const searchButton = wrapper.findAll('button').find((button) => button.text().trim() === '搜尋')
    expect(searchButton).toBeDefined()
    await searchButton!.trigger('click')
    await flushPromises()

    expect(api.searchStatutes).toHaveBeenLastCalledWith('case_1', SUGGESTED_QUERY)
    expect(api.searchStatutes).not.toHaveBeenLastCalledWith('case_1', BACKGROUND_QUERY)
  })

  it('opens the complete article in-page and exposes a link to the official source', async () => {
    const wrapper = await mountPanel()

    // jsdom's selector engine does not match a quoted attribute selector when
    // the value contains an unescaped `&`; inspect the rendered href directly.
    const officialLink = wrapper.get('a.hit-link')
    expect(officialLink.attributes('href')).toBe(OFFICIAL_URL)
    expect(officialLink.text()).toContain('洗錢防制法第6條')
    expect(officialLink.attributes('target')).toBe('_blank')
    expect(officialLink.attributes('rel')).toContain('noopener')

    const expandButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('查看完整法條'))
    expect(expandButton).toBeDefined()
    await expandButton!.trigger('click')

    expect(wrapper.text()).toContain(FULL_TEXT)
  })
})
