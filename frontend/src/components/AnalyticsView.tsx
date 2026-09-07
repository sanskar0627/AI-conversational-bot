import { useState } from 'react'
import type { AnalyticsResponse } from '../lib/types'

const GRADE_STYLES: Record<string, string> = {
  hot: 'bg-red-100 text-red-800 ring-red-200',
  warm: 'bg-amber-100 text-amber-800 ring-amber-200',
  cold: 'bg-sky-100 text-sky-800 ring-sky-200',
}

const DETAIL_FIELDS: { key: keyof AnalyticsResponse; label: string }[] = [
  { key: 'customer_name', label: 'Customer' },
  { key: 'phone', label: 'Phone' },
  { key: 'language', label: 'Language' },
  { key: 'budget_range', label: 'Budget' },
  { key: 'configuration', label: 'Configuration' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'buying_purpose', label: 'Purpose' },
  { key: 'financing', label: 'Financing' },
  { key: 'city', label: 'City' },
  { key: 'booking_status', label: 'Booking' },
  { key: 'sentiment', label: 'Sentiment' },
  { key: 'turn_count', label: 'Turns' },
]

type AnalyticsViewProps = {
  analytics: AnalyticsResponse | null
}

export function AnalyticsView({ analytics }: AnalyticsViewProps) {
  const [showRaw, setShowRaw] = useState(false)

  if (!analytics) {
    return (
      <p className="text-sm text-stone-500">
        End the conversation to generate the analytics report.
      </p>
    )
  }

  const grade = (analytics.lead_grade ?? 'cold').toLowerCase()
  const gradeStyle = GRADE_STYLES[grade] ?? GRADE_STYLES.cold
  const score = analytics.lead_score ?? 0

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <span
          className={`rounded-full px-3 py-1 text-sm font-bold uppercase tracking-wide ring-1 ${gradeStyle}`}
        >
          {grade} lead
        </span>
        {analytics.interest_level && (
          <span className="text-sm text-stone-600">
            Interest: <span className="font-semibold">{analytics.interest_level}</span>
          </span>
        )}
      </div>

      <div>
        <div className="mb-1 flex items-center justify-between text-xs text-stone-500">
          <span className="font-medium uppercase tracking-wide">Lead score</span>
          <span className="font-semibold text-stone-700">{score}/100</span>
        </div>
        <div
          role="progressbar"
          aria-valuenow={score}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Lead score"
          className="h-2 overflow-hidden rounded-full bg-stone-200"
        >
          <div
            className="h-full rounded-full bg-indigo-900 transition-all"
            style={{ width: `${Math.min(100, Math.max(0, score))}%` }}
          />
        </div>
      </div>

      {analytics.follow_up_required && (
        <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          Follow-up required{analytics.follow_up_reason ? `: ${analytics.follow_up_reason}` : ''}
        </p>
      )}

      {analytics.stop_requested && (
        <p className="rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-sm text-stone-700">
          The customer asked to stop communication. No further contact.
        </p>
      )}

      {analytics.summary && (
        <p className="rounded-md bg-stone-50 px-3 py-2 text-sm leading-relaxed text-stone-700">
          {analytics.summary}
        </p>
      )}

      <dl className="grid grid-cols-2 gap-x-3 gap-y-2">
        {DETAIL_FIELDS.map(({ key, label }) => {
          const value = analytics[key]
          if (value === null || value === undefined || value === '') return null
          return (
            <div key={key}>
              <dt className="text-[11px] uppercase tracking-wide text-stone-400">{label}</dt>
              <dd className="text-sm font-medium text-stone-800">{String(value)}</dd>
            </div>
          )
        })}
      </dl>

      <div>
        <button
          type="button"
          onClick={() => setShowRaw((current) => !current)}
          aria-expanded={showRaw}
          className="text-xs font-medium text-indigo-900 underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-900"
        >
          {showRaw ? 'Hide raw JSON' : 'Show raw JSON'}
        </button>
        {showRaw && (
          <pre className="mt-2 max-h-64 overflow-auto rounded-md bg-stone-900 p-3 text-[11px] leading-relaxed text-stone-100">
            {JSON.stringify(analytics, null, 2)}
          </pre>
        )}
      </div>
    </div>
  )
}
