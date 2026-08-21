import type { ChatMessage } from '../lib/types'

const LANGUAGE_BADGES: Record<string, { label: string; lang: string }> = {
  english: { label: 'EN', lang: 'en' },
  hindi: { label: 'HI', lang: 'hi' },
  hinglish: { label: 'Hinglish', lang: 'hi' },
}

function formatTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

type MessageBubbleProps = {
  message: ChatMessage
  onRetry: (messageId: string) => void
}

export function MessageBubble({ message, onRetry }: MessageBubbleProps) {
  const isAgent = message.role === 'agent'
  const badge = message.language ? LANGUAGE_BADGES[message.language] : undefined

  return (
    <div className={`flex ${isAgent ? 'justify-start' : 'justify-end'}`}>
      {isAgent && (
        <div
          aria-hidden="true"
          className="mr-2 mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-950 text-xs font-semibold text-amber-300"
        >
          A
        </div>
      )}
      <div className={`max-w-[80%] ${isAgent ? '' : 'text-right'}`}>
        <div
          lang={badge?.lang ?? 'en'}
          className={`inline-block rounded-2xl px-4 py-2 text-left text-sm leading-relaxed shadow-sm ${
            isAgent
              ? 'rounded-tl-sm bg-white text-stone-800 ring-1 ring-stone-200'
              : 'rounded-tr-sm bg-indigo-950 text-white'
          }`}
        >
          <p className="whitespace-pre-wrap">{message.text}</p>
          {message.retryable && (
            <button
              type="button"
              onClick={() => onRetry(message.id)}
              className="mt-2 rounded-md bg-amber-100 px-2 py-1 text-xs font-medium text-amber-900 hover:bg-amber-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-600"
            >
              That took too long — tap to retry
            </button>
          )}
        </div>
        <div
          className={`mt-1 flex items-center gap-2 text-[11px] text-stone-400 ${
            isAgent ? '' : 'justify-end'
          }`}
        >
          <span>{isAgent ? 'Aisha' : 'You'}</span>
          {badge && (
            <span className="rounded-full bg-stone-200 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-stone-600">
              {badge.label}
            </span>
          )}
          <time dateTime={message.timestamp}>{formatTime(message.timestamp)}</time>
        </div>
      </div>
    </div>
  )
}
