export function TypingIndicator() {
  return (
    <div className="flex items-center" aria-label="Aisha is typing">
      <div
        aria-hidden="true"
        className="mr-2 flex h-8 w-8 items-center justify-center rounded-full bg-indigo-950 text-xs font-semibold text-amber-300"
      >
        A
      </div>
      <div className="flex items-center gap-1 rounded-2xl rounded-tl-sm bg-white px-4 py-3 ring-1 ring-stone-200">
        {[0, 1, 2].map((dot) => (
          <span
            key={dot}
            className="h-2 w-2 animate-bounce rounded-full bg-stone-400"
            style={{ animationDelay: `${dot * 150}ms` }}
          />
        ))}
      </div>
    </div>
  )
}
