// 知識庫的法條原文是由 PDF 抽取而來，內含「依版面寬度硬換行」的斷句
// （例如「空氣污染防制計\n畫」）。這些換行不是條文本身的段落結構，直接
// 以 pre-wrap 呈現會出現奇怪的斷句。
//
// normalizeLegalText 只把「明顯是版面折行」的換行接回去，保留真正的段落
// 分隔：條列項次（1 / 一、/ （一）/ 1.）與句末標點後的換行。
// 這是顯示層的清理，不修改後端資料，也不改變法律文字內容。

// 一行的開頭若命中這些樣式，視為新的條列項目，前面的換行要保留。
const LIST_START = /^\s*(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十\d]+）|\(?\d+\)?[.、\s]|[①-⑳])/

// 句末標點：其後的換行視為段落分隔，保留。
const SENTENCE_END = /[。！？；：」』）】.!?;]$/

export function normalizeLegalText(input: string): string {
  if (!input) return ''
  // 統一換行、去除行尾空白
  const lines = input.replace(/\r\n?/g, '\n').split('\n')
  const out: string[] = []

  for (let i = 0; i < lines.length; i += 1) {
    const cur = (lines[i] ?? '').trimEnd()

    if (i === 0) {
      out.push(cur)
      continue
    }

    const prev = out[out.length - 1] ?? ''
    const trimmedCur = cur.trimStart()

    const isBlank = trimmedCur === ''
    const startsList = LIST_START.test(trimmedCur)
    const prevEndsSentence = SENTENCE_END.test(prev)

    if (isBlank || startsList || prevEndsSentence || prev === '') {
      // 保留為新的一行／段落
      out.push(cur)
    } else {
      // 版面折行：接回上一行（中文之間不補空白）
      out[out.length - 1] = prev + trimmedCur
    }
  }

  return out.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}
