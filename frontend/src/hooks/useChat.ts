import { useCallback, useEffect, useState } from 'react'
import {
  ERROR_BACKEND_UNREACHABLE,
  ERROR_CREDITS_EXHAUSTED,
  ERROR_SESSION_EXPIRED,
  sendChatMessage,
  toApiError,
} from '../lib/api'
import type {
  BookingResponse,
  BookingSnapshot,
  ChatMessage,
  MemorySnapshot,
  MessageRole,
} from '../lib/types'

export type BannerKind = 'credits' | 'offline'

type UseChatOptions = {
  greeting: string | null
  enabled: boolean
  onBanner: (kind: BannerKind | null) => void
  onSessionExpired: () => void
}

function makeMessage(role: MessageRole, text: string, language: string | null): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role,
    text,
    language,
    timestamp: new Date().toISOString(),
    retryable: false,
  }
}

function emptyBookingSnapshot(): BookingSnapshot {
  return {
    status: 'none',
    slot: null,
    confirmation_id: null,
    failure_count: 0,
    history: [],
    reason: null,
    alternatives: [],
    offered_slots: [],
    follow_up_required: false,
    follow_up_reason: null,
    validation_attempts: 0,
  }
}

export function useChat(
  sessionId: string | null,
  { greeting, enabled, onBanner, onSessionExpired }: UseChatOptions,
) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [typing, setTyping] = useState(false)
  const [memory, setMemory] = useState<MemorySnapshot | null>(null)
  const [booking, setBooking] = useState<BookingSnapshot | null>(null)

  useEffect(() => {
    setMessages(greeting ? [makeMessage('agent', greeting, 'english')] : [])
    setMemory(null)
    setBooking(null)
    setTyping(false)
  }, [sessionId, greeting])

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!sessionId || !enabled || !trimmed) return

      const userMessage = makeMessage('user', trimmed, null)
      setMessages((prev) => [...prev, userMessage])
      setTyping(true)
      try {
        const response = await sendChatMessage(sessionId, trimmed)
        setMessages((prev) => [
          ...prev,
          makeMessage('agent', response.reply, response.language),
        ])
        setMemory(response.memory_snapshot)
        setBooking(response.booking)
      } catch (cause) {
        const error = toApiError(cause)
        if (error.code === ERROR_CREDITS_EXHAUSTED) {
          onBanner('credits')
        } else if (error.code === ERROR_SESSION_EXPIRED || error.status === 410) {
          onSessionExpired()
        } else {
          if (error.code === ERROR_BACKEND_UNREACHABLE) {
            onBanner('offline')
          }
          if (error.retryable) {
            setMessages((prev) =>
              prev.map((message) =>
                message.id === userMessage.id ? { ...message, retryable: true } : message,
              ),
            )
          } else {
            setMessages((prev) => [
              ...prev,
              makeMessage('agent', `Sorry, something went wrong: ${error.message}`, null),
            ])
          }
        }
      } finally {
        setTyping(false)
      }
    },
    [sessionId, enabled, onBanner, onSessionExpired],
  )

  const retry = useCallback(
    (messageId: string) => {
      const target = messages.find((message) => message.id === messageId)
      if (!target || !target.retryable) return
      setMessages((prev) => prev.filter((message) => message.id !== messageId))
      void send(target.text)
    },
    [messages, send],
  )

  const applyBookingResult = useCallback((result: BookingResponse, requestedSlot: string) => {
    setBooking((prev) => {
      const base = prev ?? emptyBookingSnapshot()
      if (result.success) {
        return {
          ...base,
          status: 'confirmed',
          slot: result.slot ?? requestedSlot,
          confirmation_id: result.confirmation_id,
          reason: null,
          alternatives: [],
        }
      }
      return {
        ...base,
        status: 'failed',
        reason: result.reason,
        alternatives: result.alternatives ?? [],
        failure_count: base.failure_count + 1,
      }
    })
  }, [])

  return { messages, typing, memory, booking, send, retry, applyBookingResult }
}
