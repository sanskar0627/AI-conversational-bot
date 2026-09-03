import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, createSession, endSession, toApiError } from '../lib/api'
import type { AnalyticsResponse } from '../lib/types'

export type SessionStatus = 'creating' | 'active' | 'ending' | 'ended' | 'expired' | 'failed'

export function useSession() {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [greeting, setGreeting] = useState<string | null>(null)
  const [status, setStatus] = useState<SessionStatus>('creating')
  const [analytics, setAnalytics] = useState<AnalyticsResponse | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const startingRef = useRef(false)

  const start = useCallback(async () => {
    if (startingRef.current) return
    startingRef.current = true
    setStatus('creating')
    setAnalytics(null)
    setError(null)
    try {
      const session = await createSession('chat')
      setSessionId(session.session_id)
      setGreeting(session.greeting)
      setStatus('active')
    } catch (cause) {
      setError(toApiError(cause))
      setStatus('failed')
    } finally {
      startingRef.current = false
    }
  }, [])

  useEffect(() => {
    void start()
  }, [start])

  const endConversation = useCallback(async (): Promise<AnalyticsResponse | null> => {
    if (!sessionId || status !== 'active') return null
    setStatus('ending')
    try {
      const result = await endSession(sessionId)
      setAnalytics(result)
      setStatus('ended')
      return result
    } catch (cause) {
      setStatus('active')
      throw toApiError(cause)
    }
  }, [sessionId, status])

  const markExpired = useCallback(() => {
    setStatus('expired')
  }, [])

  return {
    sessionId,
    greeting,
    status,
    analytics,
    error,
    start,
    endConversation,
    markExpired,
  }
}
