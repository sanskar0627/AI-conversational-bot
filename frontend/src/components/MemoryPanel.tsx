import type { MemorySnapshot, ProfileFieldSnapshot } from '../lib/types'

const CONFIDENCE_STYLES: Record<string, { dot: string; label: string }> = {
  confirmed: { dot: 'bg-emerald-500', label: 'Confirmed' },
  stated: { dot: 'bg-amber-400', label: 'Stated' },
  uncertain: { dot: 'bg-stone-300', label: 'Uncertain' },
}

const FIELD_ORDER: { key: string; label: string }[] = [
  { key: 'name', label: 'Name' },
  { key: 'phone', label: 'Phone' },
  { key: 'budget', label: 'Budget' },
  { key: 'configuration', label: 'Configuration' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'purpose', label: 'Purpose' },
  { key: 'financing', label: 'Financing' },
  { key: 'city', label: 'City' },
  { key: 'visit_interest', label: 'Visit interest' },
]

function formatBudgetAmount(value: unknown): string {
  if (typeof value === 'number') return `₹${value} Cr`
  return String(value)
}

function formatValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (key === 'visit_interest') return value ? 'Yes' : 'No'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

function resolveField(
  profile: Record<string, ProfileFieldSnapshot>,
  key: string,
): { display: string; confidence: string | null } {
  if (key === 'budget') {
    const min = profile.budget_min
    const max = profile.budget_max
    if (!min && !max) return { display: '—', confidence: null }
    const low = min?.value
    const high = max?.value
    let display = '—'
    if (low !== undefined && low !== null && low !== '' && high !== undefined && high !== null && high !== '' && low !== high) {
      display = `${formatBudgetAmount(low)} – ${formatBudgetAmount(high)}`
    } else if (low !== undefined && low !== null && low !== '') {
      display = formatBudgetAmount(low)
    } else if (high !== undefined && high !== null && high !== '') {
      display = formatBudgetAmount(high)
    }
    return { display, confidence: (min ?? max)?.confidence ?? null }
  }
  const field = profile[key]
  if (!field) return { display: '—', confidence: null }
  return { display: formatValue(key, field.value), confidence: field.confidence }
}

type MemoryPanelProps = {
  memory: MemorySnapshot | null
}

export function MemoryPanel({ memory }: MemoryPanelProps) {
  if (!memory) {
    return (
      <p className="text-sm text-stone-500">
        Send a message to start capturing lead details live.
      </p>
    )
  }

  const intents = memory.intent_history
    .map((entry) => entry.intent)
    .filter((intent): intent is string => typeof intent === 'string')

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-stone-400">
          Conversation state
        </span>
        <span className="rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-900 ring-1 ring-indigo-100">
          {memory.state}
        </span>
      </div>

      <dl className="divide-y divide-stone-100 rounded-md border border-stone-100">
        {FIELD_ORDER.map(({ key, label }) => {
          const { display, confidence } = resolveField(memory.profile, key)
          const confidenceStyle = confidence ? CONFIDENCE_STYLES[confidence] : null
          return (
            <div key={key} className="flex items-center justify-between gap-3 px-3 py-2">
              <dt className="text-xs text-stone-500">{label}</dt>
              <dd className="flex items-center gap-1.5 text-right text-sm font-medium text-stone-800">
                {confidenceStyle && display !== '—' && (
                  <span
                    title={confidenceStyle.label}
                    aria-label={`Confidence: ${confidenceStyle.label}`}
                    className={`h-1.5 w-1.5 rounded-full ${confidenceStyle.dot}`}
                  />
                )}
                {display}
              </dd>
            </div>
          )
        })}
      </dl>

      {intents.length > 0 && (
        <div>
          <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-stone-400">
            Intent history
          </h3>
          <ol className="flex flex-wrap gap-1.5">
            {intents.map((intent, index) => (
              <li
                key={`${intent}-${index}`}
                className="rounded-full bg-stone-100 px-2 py-0.5 text-[11px] font-medium text-stone-600"
              >
                {intent}
              </li>
            ))}
          </ol>
        </div>
      )}

      {memory.objections.length > 0 && (
        <div>
          <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-stone-400">
            Objections
          </h3>
          <ul className="flex flex-col gap-1 text-sm text-stone-700">
            {memory.objections.map((objection, index) => (
              <li key={index} className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className={`h-1.5 w-1.5 rounded-full ${
                    objection.resolved ? 'bg-emerald-500' : 'bg-amber-400'
                  }`}
                />
                <span>{objection.type ?? 'objection'}</span>
                <span className="text-xs text-stone-400">
                  {objection.resolved ? 'resolved' : 'open'}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
