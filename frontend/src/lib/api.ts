import type {
  AnalyticsResponse,
  BookingResponse,
  Channel,
  ChatResponse,
  ErrorResponse,
  HealthResponse,
  SessionResponse,
  SlotsResponse,
} from './types'

export const ERROR_CREDITS_EXHAUSTED = 'CREDITS_EXHAUSTED'
export const ERROR_BACKEND_UNREACHABLE = 'BACKEND_UNREACHABLE'
export const ERROR_SESSION_EXPIRED = 'SESSION_EXPIRED'

export class ApiError extends Error {
  readonly code: string
  readonly retryable: boolean
  readonly status: number

  constructor(code: string, message: string, retryable: boolean, status: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.retryable = retryable
    this.status = status
  }
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error
  }
  const message = error instanceof Error ? error.message : 'Something went wrong'
  return new ApiError('INTERNAL_ERROR', message, false, 0)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    throw new ApiError(
      ERROR_BACKEND_UNREACHABLE,
      'Server not reachable — is the backend running?',
      true,
      0,
    )
  }

  if (!response.ok) {
    let code = 'INTERNAL_ERROR'
    let message = `Request failed (${response.status})`
    let retryable = response.status >= 500
    try {
      const body = (await response.json()) as Partial<ErrorResponse>
      if (typeof body.error_code === 'string') code = body.error_code
      if (typeof body.message === 'string') message = body.message
      if (typeof body.retryable === 'boolean') retryable = body.retryable
    } catch {
      // keep the defaults when the body is not the error contract
    }
    throw new ApiError(code, message, retryable, response.status)
  }

  return (await response.json()) as T
}

export function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/api/health')
}

export function createSession(channel: Channel = 'chat'): Promise<SessionResponse> {
  return request<SessionResponse>('/api/session', {
    method: 'POST',
    body: JSON.stringify({ channel }),
  })
}

export function sendChatMessage(sessionId: string, message: string): Promise<ChatResponse> {
  return request<ChatResponse>('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, message }),
  })
}

export function fetchSlots(sessionId: string): Promise<SlotsResponse> {
  return request<SlotsResponse>(`/api/booking/slots?session_id=${encodeURIComponent(sessionId)}`)
}

export function bookSiteVisit(
  sessionId: string,
  name: string,
  phone: string,
  slotId: string,
): Promise<BookingResponse> {
  return request<BookingResponse>('/api/book-site-visit', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, name, phone, slot_id: slotId }),
  })
}

export function endSession(sessionId: string): Promise<AnalyticsResponse> {
  return request<AnalyticsResponse>('/api/end-session', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId }),
  })
}

export function fetchAnalytics(sessionId: string): Promise<AnalyticsResponse> {
  return request<AnalyticsResponse>(`/api/analytics/${encodeURIComponent(sessionId)}`)
}
