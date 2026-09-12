import { describe, it, expect } from 'vitest'
import { formatRunEvents } from '@/utils/runEvents'
import type { RunEvent } from '@/api/caseapi'

function event(overrides: Partial<RunEvent>): RunEvent {
  return {
    sequence: 1,
    event_type: 'run.started',
    tool_call_id: null,
    timestamp: '2026-09-13T00:00:00Z',
    payload: {},
    ...overrides,
  }
}

describe('formatRunEvents', () => {
  it('pairs a search_knowledge tool.started with its tool.completed into one line', () => {
    const events = [
      event({
        sequence: 1,
        event_type: 'tool.started',
        tool_call_id: 'call_1',
        payload: { tool: 'search_knowledge', inputs: { query: '訴願期間多久' } },
      }),
      event({
        sequence: 2,
        event_type: 'tool.completed',
        tool_call_id: 'call_1',
        payload: { classification: 'search_hit', hit_count: 3 },
      }),
    ]

    const lines = formatRunEvents(events)

    expect(lines).toEqual([{ key: '2', text: '🔍 搜尋「訴願期間多久」→ 命中 3 筆' }])
  })

  it('describes an open_source completion with the chunk id it opened', () => {
    const events = [
      event({
        sequence: 1,
        event_type: 'tool.started',
        tool_call_id: 'call_2',
        payload: { tool: 'open_source', inputs: { chunk_id: 'chk_law_14' } },
      }),
      event({
        sequence: 2,
        event_type: 'tool.completed',
        tool_call_id: 'call_2',
        payload: { classification: 'opened_source', evidence_id: 'evid_1' },
      }),
    ]

    const lines = formatRunEvents(events)

    expect(lines).toEqual([{ key: '2', text: '📖 開啟原文並核對逐字：chk_law_14' }])
  })

  it('reports a generated draft proposal with the real group count', () => {
    const events = [
      event({
        sequence: 7,
        event_type: 'proposal.ready',
        payload: { proposal_id: 'prop_1', group_ids: ['draft_full_1'] },
      }),
    ]

    const lines = formatRunEvents(events)

    expect(lines).toEqual([{ key: '7', text: '🧩 產生草稿提案：1 個修改組（尚未採用）' }])
  })

  it('ignores run.started/run.completed/answer.delta bookkeeping events', () => {
    const events = [
      event({ sequence: 1, event_type: 'run.started' }),
      event({ sequence: 2, event_type: 'answer.delta', payload: { delta: 'x' } }),
      event({ sequence: 3, event_type: 'run.completed' }),
    ]

    expect(formatRunEvents(events)).toEqual([])
  })

  it('does not invent a line for a tool.completed whose tool.started is missing', () => {
    const events = [
      event({
        sequence: 1,
        event_type: 'tool.completed',
        tool_call_id: 'call_missing',
        payload: { classification: 'search_hit', hit_count: 5 },
      }),
    ]

    // No matching tool.started means we don't know which tool this was —
    // showing "搜尋「」→ 5 筆" would be worse than showing nothing.
    expect(formatRunEvents(events)).toEqual([])
  })

  it('flags a failed tool call without claiming to know what it returned', () => {
    const events = [event({ sequence: 1, event_type: 'tool.failed', tool_call_id: 'call_3' })]

    expect(formatRunEvents(events)).toEqual([
      { key: '1', text: '⚠️ 一個工具呼叫失敗了' },
    ])
  })
})
