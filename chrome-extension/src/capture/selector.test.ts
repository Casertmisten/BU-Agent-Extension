import { describe, it, expect, beforeEach } from 'vitest'
import { buildElementRef, bestSelector, xpathFor } from './selector'

describe('selector', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('bestSelector 优先用 id', () => {
    const el = document.createElement('button')
    el.id = 'submit-btn'
    document.body.appendChild(el)
    expect(bestSelector(el)).toBe('#submit-btn')
  })

  it('bestSelector 用 data-testid', () => {
    const el = document.createElement('button')
    el.setAttribute('data-testid', 'login')
    document.body.appendChild(el)
    expect(bestSelector(el)).toBe('[data-testid="login"]')
  })

  it('xpathFor 生成层级路径', () => {
    document.body.innerHTML = '<div><span><button>OK</button></span></div>'
    const btn = document.querySelector('button')!
    expect(xpathFor(btn)).toBe('/html/body/div/span/button')
  })

  it('buildElementRef 包含 tag/selector/xpath', () => {
    const el = document.createElement('input')
    el.type = 'email'
    el.id = 'email'
    document.body.appendChild(el)
    const ref = buildElementRef(el)
    expect(ref.tag).toBe('input')
    expect(ref.inputType).toBe('email')
    expect(ref.selector).toBe('#email')
    expect(ref.xpath).toContain('input')
  })

  it('buildElementRef text 截断到 120 字符', () => {
    const el = document.createElement('div')
    el.textContent = 'x'.repeat(200)
    document.body.appendChild(el)
    const ref = buildElementRef(el)
    expect(ref.text!.length).toBeLessThanOrEqual(120)
  })
})
