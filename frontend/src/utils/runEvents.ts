// 把真實的 run 事件轉成側邊欄能顯示的一行活動紀錄。
// 內容全部來自後端事件，不自己編——只有動畫節奏（思考中/查詢中）是前端假的，
// 「查了哪些資料」這幾行文字每一個字都對應真的 tool.started/completed 事件。
import type { RunEvent } from '@/api/caseapi'

export interface ActivityLine {
  key: string
  text: string
}

export function formatRunEvents(events: RunEvent[]): ActivityLine[] {
  const startedByCallId = new Map<string, RunEvent>()
  const lines: ActivityLine[] = []

  for (const event of events) {
    if (event.event_type === 'tool.started' && event.tool_call_id) {
      startedByCallId.set(event.tool_call_id, event)
      continue
    }
    if (event.event_type === 'tool.completed' && event.tool_call_id) {
      const line = formatCompletedTool(event, startedByCallId.get(event.tool_call_id))
      if (line) lines.push(line)
      continue
    }
    if (event.event_type === 'tool.failed') {
      lines.push({ key: String(event.sequence), text: '⚠️ 一個工具呼叫失敗了' })
      continue
    }
    if (event.event_type === 'proposal.ready') {
      const groupIds = Array.isArray(event.payload.group_ids) ? event.payload.group_ids : []
      lines.push({
        key: String(event.sequence),
        text: `🧩 產生草稿提案：${groupIds.length} 個修改組（尚未採用）`,
      })
    }
  }
  return lines
}

function formatCompletedTool(event: RunEvent, started: RunEvent | undefined): ActivityLine | null {
  const startedPayload = (started?.payload ?? {}) as { tool?: string; inputs?: Record<string, unknown> }
  const tool = startedPayload.tool
  const inputs = startedPayload.inputs ?? {}
  const key = String(event.sequence)

  if (tool === 'search_knowledge') {
    const query = typeof inputs.query === 'string' ? inputs.query : ''
    const hitCount = typeof event.payload.hit_count === 'number' ? event.payload.hit_count : 0
    return { key, text: `🔍 搜尋「${query}」→ 命中 ${hitCount} 筆` }
  }
  if (tool === 'open_source') {
    const chunkId = typeof inputs.chunk_id === 'string' ? inputs.chunk_id : ''
    return { key, text: `📖 開啟原文並核對逐字：${chunkId}` }
  }
  if (tool === 'read_selection_context') {
    return { key, text: '📎 讀取選取範圍' }
  }
  return null
}
