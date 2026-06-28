/** 隐私脱敏（简化自 Browser-BC redaction/redactor.ts）。
 *  保留密码/邮箱/电话/支付/OTP 的分类与 raw_removed 策略。
 *  去掉 identity_bundle 匹配、网络 body 分类、dom_snapshot 处理。 */

import type { RedactedValue, RedactionClass } from './types'

type RedactionContext = {
  fieldName?: string
  inputType?: string
}

const LARGE_BODY_LIMIT = 4096
const EMAIL_RE = /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i
const PHONE_RE = /(?:\+?\d[\s().-]*){7,15}/
const DIGIT_RE = /\d/g
const OTP_RE = /\b\d{4,8}\b/
const PASSWORD_FIELD_RE = /pass(word)?|pwd|secret/i
const EMAIL_FIELD_RE = /e-?mail/i
const PHONE_FIELD_RE = /phone|mobile|tel/i
const PAYMENT_FIELD_RE = /card|cc|cvc|cvv|payment|expir(y|ation|e)?|exp_(month|year)/i
const OTP_CONTEXT_RE = /otp|one[-_\s]?time|verification|verify|2fa|mfa|code/i

export function redactText(value: string, context: RedactionContext = {}): RedactedValue {
  const classes = classifyText(value, context)
  if (classes.length === 0) {
    return { value }
  }
  return {
    value: null,
    redaction: {
      strategy: 'raw_removed',
      classes,
      digest: digestFor(value),
      originalLength: value.length,
    },
  }
}

function classifyText(value: string, context: RedactionContext): RedactionClass[] {
  const classes: RedactionClass[] = []
  const field = `${context.fieldName ?? ''} ${context.inputType ?? ''}`

  if (value.length > LARGE_BODY_LIMIT) {
    classes.push('classified_token')
  }

  if (PASSWORD_FIELD_RE.test(field) || context.inputType?.toLowerCase() === 'password') {
    classes.push('classified_password')
  }
  if (EMAIL_FIELD_RE.test(field)) {
    classes.push('classified_email')
  }
  if (PHONE_FIELD_RE.test(field)) {
    classes.push('classified_phone')
  }
  if (PAYMENT_FIELD_RE.test(field)) {
    classes.push('classified_payment')
  }
  if (OTP_CONTEXT_RE.test(field) && OTP_RE.test(value)) {
    classes.push('classified_otp')
  }

  if (EMAIL_RE.test(value)) {
    classes.push('classified_email')
  }

  const digits = digitsOnly(value)
  if (digits.length >= 13 && digits.length <= 19 && luhnValid(digits)) {
    classes.push('classified_payment')
  } else if (PHONE_RE.test(value) && digits.length >= 7 && digits.length <= 15) {
    classes.push('classified_phone')
  }

  return [...new Set(classes)]
}

function digitsOnly(value: string): string {
  return Array.from(String(value).matchAll(DIGIT_RE), (m) => m[0]).join('')
}

function luhnValid(value: string): boolean {
  let sum = 0
  let doubleDigit = false
  for (let i = value.length - 1; i >= 0; i -= 1) {
    let digit = Number(value[i])
    if (doubleDigit) {
      digit *= 2
      if (digit > 9) digit -= 9
    }
    sum += digit
    doubleDigit = !doubleDigit
  }
  return sum > 0 && sum % 10 === 0
}

/** FNV-1a 32 位 hash（同步，不依赖 SubtleCrypto）。 */
function digestFor(value: string): string {
  let hash = 0x811c9dc5
  for (let i = 0; i < value.length; i++) {
    hash ^= value.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193)
  }
  return `fnv1a:${(hash >>> 0).toString(16).padStart(8, '0')}`
}
