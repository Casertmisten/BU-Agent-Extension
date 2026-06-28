import { describe, it, expect } from 'vitest'
import { redactText } from './redactor'

describe('redactText', () => {
  it('普通文本不脱敏', () => {
    const r = redactText('hello world', {})
    expect(r.value).toBe('hello world')
    expect(r.redaction).toBeUndefined()
  })

  it('密码字段脱敏', () => {
    const r = redactText('secret123', { fieldName: 'password', inputType: 'password' })
    expect(r.value).toBeNull()
    expect(r.redaction?.classes).toContain('classified_password')
  })

  it('邮箱值脱敏', () => {
    const r = redactText('user@example.com', { fieldName: 'email' })
    expect(r.value).toBeNull()
    expect(r.redaction?.classes).toContain('classified_email')
  })

  it('邮箱正则匹配脱敏', () => {
    const r = redactText('联系 admin@test.com 谢谢', {})
    expect(r.value).toBeNull()
    expect(r.redaction?.classes).toContain('classified_email')
  })

  it('支付卡号脱敏（Luhn 有效）', () => {
    const r = redactText('4111111111111111', {})
    expect(r.value).toBeNull()
    expect(r.redaction?.classes).toContain('classified_payment')
  })

  it('OTP 上下文脱敏', () => {
    const r = redactText('123456', { fieldName: 'verification_code' })
    expect(r.value).toBeNull()
    expect(r.redaction?.classes).toContain('classified_otp')
  })
})
