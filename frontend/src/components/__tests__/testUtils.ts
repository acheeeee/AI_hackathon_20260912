// `flushPromises()`（@vue/test-utils）只等一個 macrotask tick（見其原始碼：
// `setImmediate(resolve, 0)`）。組 DraftBlockTarget 時會呼叫
// `crypto.subtle.digest`，Node 的 WebCrypto 實作把雜湊算在 thread pool，
// 完成回呼不保證在同一個 tick 內跑完——單靠一次 flushPromises 偶爾會在候選
// 還沒 emit 前就斷言，造成間歇性失敗。這裡改成反覆 flush 直到條件成立或逾時。

import { flushPromises } from '@vue/test-utils'

export async function waitForCondition(
  condition: () => boolean,
  { timeoutMs = 2000, stepMs = 10 }: { timeoutMs?: number; stepMs?: number } = {},
): Promise<void> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    await flushPromises()
    if (condition()) return
    if (Date.now() >= deadline) {
      throw new Error('waitForCondition timed out')
    }
    await new Promise((resolve) => setTimeout(resolve, stepMs))
  }
}
