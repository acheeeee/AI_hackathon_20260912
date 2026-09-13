import { describe, it, expect } from 'vitest'
import {
  utf16RangeToCodepointRange,
  sha256Hex,
  buildDraftBlockTarget,
} from '@/utils/draftSelection'

describe('utf16RangeToCodepointRange', () => {
  it('keeps ASCII/CJK offsets unchanged when every character is in the BMP', () => {
    const text = '訴願人主張原處分違法。'
    const utf16Start = text.indexOf('原處分')
    const utf16End = utf16Start + '原處分'.length
    expect(utf16RangeToCodepointRange(text, utf16Start, utf16End)).toEqual({
      start: utf16Start,
      end: utf16End,
    })
  })

  it('locates the second occurrence of a repeated phrase, not the first', () => {
    const phrase = '原處分機關認事用法並無違誤'
    const text = `${phrase}。${phrase}，故本件無理由。`
    const firstStart = text.indexOf(phrase)
    const secondStart = text.indexOf(phrase, firstStart + 1)
    const secondEnd = secondStart + phrase.length

    const range = utf16RangeToCodepointRange(text, secondStart, secondEnd)

    expect(text.slice(secondStart, secondEnd)).toBe(phrase)
    expect(range.start).not.toBe(firstStart)
    expect(Array.from(text).slice(range.start, range.end).join('')).toBe(phrase)
  })

  it('does not split a surrogate pair when a selection starts after a non-BMP character', () => {
    const emoji = '\u{1F4C4}' // single codepoint, 2 UTF-16 code units
    const text = `${emoji}附件已上傳`
    const utf16Start = emoji.length // right after the surrogate pair, in UTF-16 units
    const utf16End = text.length

    const range = utf16RangeToCodepointRange(text, utf16Start, utf16End)
    const codepoints = Array.from(text)

    expect(codepoints.length).toBe(1 + '附件已上傳'.length)
    expect(range.start).toBe(1)
    expect(codepoints.slice(range.start, range.end).join('')).toBe('附件已上傳')
  })
})

describe('sha256Hex', () => {
  it('matches the well-known sha256 of an empty string', async () => {
    expect(await sha256Hex('')).toBe(
      'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    )
  })

  it('hashes UTF-8 bytes, not UTF-16 code units, for non-ASCII text', async () => {
    // sha256("原處分") computed independently via python: hashlib.sha256('原處分'.encode()).hexdigest()
    expect(await sha256Hex('原處分')).toBe(
      '88d5ba58de494a3a1086ccaabd18cb488dbf4611cac36a2efd8bfeddd4441835',
    )
  })
})

describe('buildDraftBlockTarget', () => {
  it('builds a target whose char range and hash match the selected substring', async () => {
    const phrase = '原處分機關認事用法並無違誤'
    const blockText = `${phrase}。${phrase}，故本件無理由。`
    const secondStart = blockText.indexOf(phrase, blockText.indexOf(phrase) + 1)
    const secondEnd = secondStart + phrase.length

    const target = await buildDraftBlockTarget({
      resourceId: 'draft_1',
      resourceRevision: 'res_1',
      blockId: 'reason-1',
      blockText,
      utf16Start: secondStart,
      utf16End: secondEnd,
    })

    expect(target.kind).toBe('draft_block')
    expect(target.selected_text).toBe(phrase)
    expect(target.char_end - target.char_start).toBe(Array.from(phrase).length)
    expect(target.char_start).not.toBe(0)
  })
})
