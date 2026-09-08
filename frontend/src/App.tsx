import { useCallback, useEffect, useState } from 'react'
import { AnalyticsView } from './components/AnalyticsView'
import { BookingCard } from './components/BookingCard'
import { ChatInput } from './components/ChatInput'
import { ChatWindow } from './components/ChatWindow'
import { ErrorBanner } from './components/ErrorBanner'
import { MemoryPanel } from './components/MemoryPanel'
import { SessionModal } from './components/SessionModal'
import { useChat } from './hooks/useChat'
import type { BannerKind } from './hooks/useChat'
import { useSession } from './hooks/useSession'
import { bookSiteVisit, fetchHealth, fetchSlots, toApiError } from './lib/api'
import type { HealthResponse, SlotInfo } from './lib/types'

const HEALTH_POLL_INTERVAL_MS = 30_000

type HealthStatus = 'checking' | 'ok' | 'degraded' | 'down'

const STATUS_STYLES: Record<HealthStatus, { dot: string; label: string }> = {
  checking: { dot: 'bg-stone-300', label: 'Checking…' },
  ok: { dot: 'bg-emerald-500', label: 'Online' },
  degraded: { dot: 'bg-amber-500', label: 'Degraded' },
  down: { dot: 'bg-red-500', label: 'Offline' },
}

type InsightTab = 'memory' | 'booking' | 'analytics'

const TABS: { id: InsightTab; label: string }[] = [
  { id: 'memory', label: 'Memory' },
  { id: 'booking', label: 'Booking' },
  { id: 'analytics', label: 'Analytics' },
]

function App() {
  const session = useSession()
  const [banner, setBanner] = useState<BannerKind | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [healthStatus, setHealthStatus] = useState<HealthStatus>('checking')
  const [activeTab, setActiveTab] = useState<InsightTab>('memory')
  const [slots, setSlots] = useState<SlotInfo[]>([])
  const [bookingBusy, setBookingBusy] = useState(false)

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

  useEffect(() => {
    if (session.status !== 'active' || !session.sessionId) return
    let cancelled = false
    fetchSlots(session.sessionId)
      .then((response) => {
        if (!cancelled) setSlots(response.slots)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [session.status, session.sessionId])

  const handleBook = useCallback(
    async (slotId: string, name: string, phone: string) => {
      if (!session.sessionId || bookingBusy) return
      setBookingBusy(true)
      try {
        const result = await bookSiteVisit(session.sessionId, name, phone, slotId)
        chat.applyBookingResult(result, slotId)
      } catch (cause) {
        const error = toApiError(cause)
        if (error.code === 'CREDITS_EXHAUSTED') setBanner('credits')
        else if (error.code === 'BACKEND_UNREACHABLE') setBanner('offline')
        else if (error.code === 'SESSION_EXPIRED' || error.status === 410) session.markExpired()
      } finally {
        setBookingBusy(false)
      }
    },
    [session, bookingBusy, chat],
  )

  const handleEndConversation = useCallback(async () => {
    try {
      const result = await session.endConversation()
      if (result) setActiveTab('analytics')
    } catch (cause) {
      const error = toApiError(cause)
      if (error.code === 'BACKEND_UNREACHABLE') setBanner('offline')
      else if (error.code === 'SESSION_EXPIRED' || error.status === 410) session.markExpired()
    }
  }, [session])

  const handleNewConversation = useCallback(() => {
    setSlots([])
    setActiveTab('memory')
    setBanner(null)
    void session.start()
  }, [session])

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
        <div className="flex items-center gap-4">
          {(session.status === 'ended' || session.status === 'expired') && (
            <button
              type="button"
              onClick={handleNewConversation}
              className="rounded-lg bg-indigo-950 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-950"
            >
              New conversation
            </button>
          )}
          <div className="flex items-center gap-2 text-sm text-stone-500">
            <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-full ${statusStyle.dot}`} />
            <span role="status">{statusStyle.label}</span>
            {health && (
              <span className="hidden text-xs text-stone-400 sm:inline">· {health.model}</span>
            )}
          </div>
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
            onEndConversation={() => void handleEndConversation()}
          />
        </section>

        <aside
          aria-label="Insights"
          className="flex flex-col rounded-lg border border-stone-200 bg-white shadow-sm"
        >
          <div role="tablist" aria-label="Insight panels" className="flex border-b border-stone-200">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex-1 px-3 py-2.5 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-indigo-900 ${
                  activeTab === tab.id
                    ? 'border-b-2 border-indigo-950 text-indigo-950'
                    : 'text-stone-500 hover:text-stone-700'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div role="tabpanel" className="flex-1 p-4">
            {activeTab === 'memory' && <MemoryPanel memory={chat.memory} />}
            {activeTab === 'booking' && (
              <BookingCard
                booking={chat.booking}
                memory={chat.memory}
                slots={slots}
                busy={bookingBusy}
                disabled={session.status !== 'active'}
                onBook={(slotId, name, phone) => void handleBook(slotId, name, phone)}
                onCancel={() => void chat.send('I want to cancel my site visit')}
              />
            )}
            {activeTab === 'analytics' && <AnalyticsView analytics={session.analytics} />}
          </div>
        </aside>
      </main>

      {session.status === 'expired' && <SessionModal onNewSession={handleNewConversation} />}
    </div>
  )
}

export default App
