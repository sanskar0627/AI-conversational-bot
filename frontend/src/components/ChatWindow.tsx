import { useEffect, useRef } from 'react'
import type { ChatMessage } from '../lib/types'
import { MessageBubble } from './MessageBubble'
import { TypingIndicator } from './TypingIndicator'

type ChatWindowProps = {
  messages: ChatMessage[]
  typing: boolean
  onRetry: (messageId: string) => void
}

export function ChatWindow({ messages, typing, onRetry }: ChatWindowProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = scrollRef.current
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
    }
  }, [messages.length, typing])

  return (
    <div
      ref={scrollRef}
      role="log"
      aria-live="polite"
      aria-label="Conversation with Aisha"
      className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 py-4"
    >
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} onRetry={onRetry} />
      ))}
      {typing && <TypingIndicator />}
    </div>
  )
}
