import { useCallback, useEffect, useState } from 'react'
import { ChatInput } from './components/ChatInput'
import { ChatWindow } from './components/ChatWindow'
import { ErrorBanner } from './components/ErrorBanner'
import { useChat } from './hooks/useChat'
import type { BannerKind } from './hooks/useChat'
import { useSession } from './hooks/useSession'
import { fetchHealth } from './lib/api'
import type { HealthResponse } from './lib/types'

const HEALTH_POLL_INTERVAL_MS = 30_000

type HealthStatus = 'checking' | 'ok' | 'degraded' | 'down'

const STATUS_STYLES: Record<HealthStatus, { dot: string; label: string }> = {
  checking: { dot: 'bg-stone-300', label: 'Checking…' },
  ok: { dot: 'bg-emerald-500', label: 'Online' },
  degraded: { dot: 'bg-amber-500', label: 'Degraded' },
  down: { dot: 'bg-red-500', label: 'Offline' },
}

function App() {
  const session = useSession()
  const [banner, setBanner] = useState<BannerKind | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [healthStatus, setHealthStatus] = useState<HealthStatus>('checking')

  const chat = useChat(session.sessionId, {
    greeting: session.greeting,
    enabled: session.status === 'active' && banner !== 'credits',
    onBanner: setBanner,
    onSessionExpired: session.markExpired,
  })

  const checkHealth = useCallback(async () => {
    try {
      const result = await fetchHealth()
      setHealth(result)
      setHealthStatus(result.llm_configured ? 'ok' : 'degraded')
      setBanner((current) => (current === 'credits' ? null : current))
    } catch {
      setHealth(null)
      setHealthStatus('down')
    }
  }, [])

  useEffect(() => {
    void checkHealth()
    const timer = setInterval(() => void checkHealth(), HEALTH_POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [checkHealth])

  const chatDisabled = session.status !== 'active' || chat.typing || banner === 'credits'
  const statusStyle = STATUS_STYLES[healthStatus]

  return (
    <div className="flex min-h-screen flex-col bg-stone-100 text-stone-800">
      <header className="flex items-center justify-between border-b border-stone-200 bg-white px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-indigo-950">
            Northstar Homes — Aisha
          </h1>
          <p className="text-sm text-stone-500">Northstar One · Sector 79, Gurugram</p>
        </div>
        <div className="flex items-center gap-2 text-sm text-stone-500">
          <span
            aria-hidden="true"
            className={`h-2.5 w-2.5 rounded-full ${statusStyle.dot}`}
          />
          <span role="status">{statusStyle.label}</span>
          {health && (
            <span className="hidden text-xs text-stone-400 sm:inline">· {health.model}</span>
          )}
        </div>
      </header>

      <ErrorBanner
        kind={banner}
        onRetry={banner === 'offline' ? () => void checkHealth() : undefined}
      />

      <main className="mx-auto grid w-full max-w-6xl flex-1 grid-cols-1 gap-4 p-4 md:grid-cols-[minmax(0,1.4fr)_minmax(18rem,0.8fr)]">
        <section
          aria-label="Chat"
          className="flex min-h-[32rem] flex-col overflow-hidden rounded-lg border border-stone-200 bg-stone-50 shadow-sm"
        >
          <ChatWindow messages={chat.messages} typing={chat.typing} onRetry={chat.retry} />
          <ChatInput
            disabled={chatDisabled}
            ending={session.status === 'ending'}
            onSend={(text) => void chat.send(text)}
            onEndConversation={() => void session.endConversation()}
          />
        </section>

        <aside
          aria-label="Insights"
          className="rounded-lg border border-stone-200 bg-white p-4 shadow-sm"
        >
          <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-stone-400">
            Insights
          </h2>
          <p className="text-sm text-stone-500">
            Memory, booking, and analytics panels arrive next.
          </p>
        </aside>
      </main>
    </div>
  )
}

export default App
