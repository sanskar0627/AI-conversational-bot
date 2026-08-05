import { useEffect, useState } from 'react'
import type { HealthResponse } from './lib/types'

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Health check failed (${response.status})`)
        }
        return (await response.json()) as HealthResponse
      })
      .then(setHealth)
      .catch((error: unknown) => {
        setHealthError(error instanceof Error ? error.message : 'Health check failed')
      })
  }, [])

  return (
    <div className="min-h-screen bg-stone-50 text-stone-800">
      <header className="border-b border-stone-200 bg-white px-6 py-4">
        <h1 className="text-lg font-semibold tracking-tight">Northstar Homes</h1>
        <p className="text-sm text-stone-500">Aisha — Northstar One sales consultant</p>
      </header>

      <main className="mx-auto grid min-h-[calc(100vh-4.5rem)] max-w-6xl grid-cols-1 gap-4 p-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(18rem,0.8fr)]">
        <section className="rounded-lg border border-stone-200 bg-white p-4 shadow-sm">
          <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-stone-400">
            Chat
          </h2>
          <p className="text-sm text-stone-500">Conversation window arrives in Stage 07.</p>
        </section>

        <aside className="rounded-lg border border-stone-200 bg-white p-4 shadow-sm">
          <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-stone-400">
            Insights
          </h2>
          <p className="mb-4 text-sm text-stone-500">
            Memory, booking, and analytics panels arrive in later stages.
          </p>
          <div className="rounded-md bg-stone-50 p-3 text-sm">
            <p className="font-medium text-stone-700">API health</p>
            {health ? (
              <p className="mt-1 text-stone-600">
                {health.status} · {health.model} · LLM{' '}
                {health.llm_configured ? 'configured' : 'not configured'}
              </p>
            ) : healthError ? (
              <p className="mt-1 text-red-600">{healthError}</p>
            ) : (
              <p className="mt-1 text-stone-400">Checking…</p>
            )}
          </div>
        </aside>
      </main>
    </div>
  )
}

export default App
