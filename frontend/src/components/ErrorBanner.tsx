import type { BannerKind } from '../hooks/useChat'

type ErrorBannerProps = {
  kind: BannerKind | null
  onRetry?: () => void
}

export function ErrorBanner({ kind, onRetry }: ErrorBannerProps) {
  if (!kind) return null

  if (kind === 'credits') {
    return (
      <div
        role="alert"
        className="flex items-center justify-center gap-3 border-b border-amber-300 bg-amber-100 px-4 py-2.5 text-sm font-medium text-amber-900"
      >
        <span aria-hidden="true">⚠</span>
        <span>AI service temporarily unavailable. Please recharge the OpenRouter account.</span>
      </div>
    )
  }

  return (
    <div
      role="alert"
      className="flex items-center justify-center gap-3 border-b border-red-300 bg-red-100 px-4 py-2.5 text-sm font-medium text-red-900"
    >
      <span>Server not reachable — is the backend running?</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md bg-red-700 px-2.5 py-1 text-xs font-semibold text-white hover:bg-red-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700"
        >
          Retry
        </button>
      )}
    </div>
  )
}
