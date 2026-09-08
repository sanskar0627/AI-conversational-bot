type SessionModalProps = {
  onNewSession: () => void
}

export function SessionModal({ onNewSession }: SessionModalProps) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="session-expired-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/50 p-4"
    >
      <div className="w-full max-w-sm rounded-lg bg-white p-6 shadow-xl">
        <h2 id="session-expired-title" className="text-base font-semibold text-stone-900">
          Session expired
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-stone-600">
          This conversation timed out after being inactive. Your transcript above is still
          visible, but you will need a fresh session to keep chatting.
        </p>
        <button
          type="button"
          autoFocus
          onClick={onNewSession}
          className="mt-4 w-full rounded-lg bg-indigo-950 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-950"
        >
          Start a new conversation
        </button>
      </div>
    </div>
  )
}
