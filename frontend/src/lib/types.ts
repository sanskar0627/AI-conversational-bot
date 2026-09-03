export type HealthResponse = {
  status: string
  model: string
  llm_configured: boolean
}

export type Channel = 'chat' | 'voice'

export type SessionResponse = {
  session_id: string
  greeting: string
}

export type SlotInfo = {
  slot_id: string
  label: string
  available: boolean
}

export type SlotsResponse = {
  slots: SlotInfo[]
}

export type BookingResponse = {
  success: boolean
  confirmation_id: string | null
  slot: string | null
  slot_label: string | null
  reason: string | null
  alternatives: SlotInfo[] | null
}

export type ProfileFieldSnapshot = {
  value: unknown
  confidence: string
  last_updated_turn: number
}

export type BookingSnapshot = {
  status: string
  slot: string | null
  confirmation_id: string | null
  failure_count: number
  history: unknown[]
  reason: string | null
  alternatives: SlotInfo[]
  offered_slots: string[]
  follow_up_required: boolean
  follow_up_reason: string | null
  validation_attempts: number
}

export type IntentRecord = {
  turn?: number
  intent?: string
} & Record<string, unknown>

export type ObjectionRecord = {
  turn?: number
  type?: string
  resolved?: boolean
} & Record<string, unknown>

export type MemorySnapshot = {
  profile: Record<string, ProfileFieldSnapshot>
  state: string
  intent_history: IntentRecord[]
  objections: ObjectionRecord[]
  booking: BookingSnapshot
  language: string | null
}

export type ChatResponse = {
  reply: string
  state: string
  language: string
  memory_snapshot: MemorySnapshot
  booking: BookingSnapshot
}

export type AnalyticsResponse = {
  session_id: string
  customer_name: string | null
  phone: string | null
  language: string | null
  languages_used: string[]
  budget_range: string | null
  configuration: string | null
  timeline: string | null
  buying_purpose: string | null
  financing: string | null
  city: string | null
  interest_level: string | null
  intent_history: IntentRecord[]
  objections: ObjectionRecord[]
  booking_status: string | null
  booking_slot: string | null
  confirmation_id: string | null
  escalation: Record<string, unknown> | null
  stop_requested: boolean
  follow_up_required: boolean
  follow_up_reason: string | null
  sentiment: string | null
  conversation_duration_seconds: number | null
  turn_count: number | null
  lead_score: number | null
  lead_grade: string | null
  confidence: number | null
  summary: string | null
}

export type ErrorResponse = {
  error_code: string
  message: string
  retryable: boolean
}

export type MessageRole = 'user' | 'agent'

export type ChatMessage = {
  id: string
  role: MessageRole
  text: string
  language: string | null
  timestamp: string
  retryable: boolean
}
