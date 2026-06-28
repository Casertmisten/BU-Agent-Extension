/** 录制事件数据结构（照搬 Browser-BC 简化版，只保留 action + navigation + dom_mutation_summary）。 */

export type RedactionClass =
  | 'classified_password'
  | 'classified_email'
  | 'classified_phone'
  | 'classified_payment'
  | 'classified_otp'
  | 'classified_token'

export type RedactionStrategy =
  | 'raw_removed'
  | 'classified'

export type Redaction = {
  strategy: RedactionStrategy
  classes: RedactionClass[]
  digest?: string
  originalLength?: number
}

export type RedactedValue<T = string> = {
  value: T | null
  redaction?: Redaction
}

export type DomMutationSignal =
  | 'modal_added'
  | 'status_added'
  | 'list_changed'
  | 'form_control_enabled'
  | 'form_control_disabled'
  | 'node_removed'

/** 所有事件的公共字段 */
export type EventBase = {
  event_id: string
  trace_id: string
  tab_id: number
  timestamp: number
  url: string
}

/** 元素定位信息（distill 的关键） */
export type ElementRef = {
  tag: string
  inputType?: string
  id?: string
  classes?: string[]
  role?: string
  name?: string
  text?: string
  selector: string
  xpath: string
  rect?: { x: number; y: number; w: number; h: number }
}

/** 用户操作事件（16 种 action_type） */
export type ActionEvent = EventBase & {
  kind: 'action'
  action_type:
    | 'click'
    | 'dblclick'
    | 'input'
    | 'change'
    | 'submit'
    | 'keydown'
    | 'scroll'
    | 'drag'
    | 'drop'
    | 'focus'
    | 'blur'
    | 'contextmenu'
    | 'wheel'
    | 'copy'
    | 'cut'
    | 'selection'
    | 'file_select'
  target?: ElementRef
  value?: RedactedValue
  key?: string
  coords?: { x: number; y: number }
  modifiers?: { ctrl?: boolean; shift?: boolean; alt?: boolean; meta?: boolean }
  wheel?: { delta_x: number; delta_y: number; delta_mode: number }
  selection?: { length: number; text?: RedactedValue }
  files?: {
    count: number
    total_bytes: number
    accepted_types: string[]
    selected_types: string[]
  }
}

/** 导航事件 */
export type NavigationEvent = EventBase & {
  kind: 'navigation'
  nav_type:
    | 'load'
    | 'pushState'
    | 'replaceState'
    | 'popState'
    | 'hashChange'
    | 'beforeUnload'
  from_url?: string
  to_url?: string
}

/** DOM 变更摘要事件 */
export type DomMutationSummaryEvent = EventBase & {
  kind: 'dom_mutation_summary'
  added_nodes: number
  removed_nodes: number
  attribute_changes: number
  signals: DomMutationSignal[]
  selectors: string[]
  text_samples: RedactedValue<string[]>
}

/** 录制捕获的所有事件类型 */
export type CapturedEvent =
  | ActionEvent
  | NavigationEvent
  | DomMutationSummaryEvent
