import { describe, it, expect } from 'vitest'
import { createId } from './id'

describe('createId', () => {
  it('带前缀生成唯一 ID', () => {
    const id1 = createId('ev_')
    const id2 = createId('ev_')
    expect(id1).toMatch(/^ev_/)
    expect(id1).not.toBe(id2)
  })

  it('长度合理（前缀 + 时间戳 + 12 字节 hex）', () => {
    const id = createId('ev_')
    // ev_ + base36 时间戳 + _ + 24 hex 字符
    expect(id.length).toBeGreaterThan(10)
    expect(id.length).toBeLessThan(60)
  })
})
