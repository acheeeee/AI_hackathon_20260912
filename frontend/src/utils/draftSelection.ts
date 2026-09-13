// 把 textarea 的原生選取範圍轉成後端 DraftBlockTarget 需要的形狀。
//
// `HTMLTextAreaElement.selectionStart/End` 是 UTF-16 code unit 索引（JS 字串
// 的索引單位）；後端 Python 用 Unicode code point 索引做字串切片
// （`caseapi/schemas/target.py::DraftBlockTarget`）。多數中文字在 BMP
// （Basic Multilingual Plane，UTF-16 用一個 16-bit 單位就能表示的範圍）內，
// 兩種索引剛好相同；但 emoji 或罕見擴充字屬於 surrogate pair（一個字元要用
// 兩個 16-bit 單位才能表示），這時兩種索引就會錯開，直接把 UTF-16 索引送給
// 後端會切到不對的字元。

import type { DraftBlockTarget } from '@/api/caseapi'

export interface CodepointRange {
  start: number
  end: number
}

export function utf16RangeToCodepointRange(
  text: string,
  utf16Start: number,
  utf16End: number,
): CodepointRange {
  let utf16Offset = 0
  let codepointIndex = 0
  let start = utf16Start === 0 ? 0 : -1
  let end = utf16End === 0 ? 0 : -1

  for (const char of text) {
    if (utf16Offset === utf16Start) start = codepointIndex
    if (utf16Offset === utf16End) end = codepointIndex
    utf16Offset += char.length
    codepointIndex += 1
  }

  // 邊界落在文字最尾端時，迴圈裡不會再有下一個字元觸發上面的檢查，
  // 用跑完的 codepointIndex（等於總 code point 數）補上。
  return {
    start: start === -1 ? codepointIndex : start,
    end: end === -1 ? codepointIndex : end,
  }
}

export async function sha256Hex(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
}

export async function buildDraftBlockTarget(params: {
  resourceId: string
  resourceRevision: string
  blockId: string
  blockText: string
  utf16Start: number
  utf16End: number
}): Promise<DraftBlockTarget> {
  const selectedText = params.blockText.slice(params.utf16Start, params.utf16End)
  const { start, end } = utf16RangeToCodepointRange(
    params.blockText,
    params.utf16Start,
    params.utf16End,
  )
  return {
    kind: 'draft_block',
    resource_id: params.resourceId,
    resource_revision: params.resourceRevision,
    block_id: params.blockId,
    char_start: start,
    char_end: end,
    selected_text: selectedText,
    selected_text_sha256: await sha256Hex(selectedText),
  }
}
