import { useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'

const MAX_MESSAGE_LENGTH = 2000

type ChatInputProps = {
  disabled: boolean
  ending: boolean
  onSend: (text: string) => void
  onEndConversation: () => void
}

export function ChatInput({ disabled, ending, onSend, onEndConversation }: ChatInputProps) {
  const [draft, setDraft] = useState('')
  const [confirmingEnd, setConfirmingEnd] = useState(false)

  const submit = () => {
    const text = draft.trim()
    if (!text || disabled) return
    onSend(text)
    setDraft('')
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    submit()
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <div className="border-t border-stone-200 bg-white px-4 py-3">
      <form onSubmit={handleSubmit} className="flex items-end gap-2">
        <label htmlFor="chat-message" className="sr-only">
          Type your message
        </label>
        <textarea
          id="chat-message"
          rows={2}
          value={draft}
          maxLength={MAX_MESSAGE_LENGTH}
          disabled={disabled}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={disabled ? 'Chat is unavailable right now' : 'Type your message…'}
          className="min-h-[2.75rem] flex-1 resize-none rounded-lg border border-stone-300 px-3 py-2 text-sm text-stone-800 placeholder:text-stone-400 focus:border-indigo-900 focus:outline-none focus:ring-2 focus:ring-indigo-900/20 disabled:cursor-not-allowed disabled:bg-stone-100"
        />
        <button
          type="submit"
          disabled={disabled || !draft.trim()}
          className="rounded-lg bg-indigo-950 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-950 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Send
        </button>
      </form>
      <div className="mt-2 flex items-center justify-between text-xs text-stone-400">
        <span aria-hidden="true">
          {draft.length}/{MAX_MESSAGE_LENGTH}
        </span>
        {confirmingEnd ? (
          <span className="flex items-center gap-2">
            <span className="text-stone-500">End this conversation?</span>
            <button
              type="button"
              disabled={ending}
              onClick={() => {
                setConfirmingEnd(false)
                onEndConversation()
              }}
              className="rounded-md bg-red-700 px-2 py-1 font-medium text-white hover:bg-red-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700 disabled:opacity-50"
            >
              {ending ? 'Ending…' : 'Yes, end it'}
            </button>
            <button
              type="button"
              onClick={() => setConfirmingEnd(false)}
              className="rounded-md px-2 py-1 font-medium text-stone-600 hover:bg-stone-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stone-400"
            >
              Keep chatting
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmingEnd(true)}
            className="rounded-md px-2 py-1 font-medium text-stone-500 hover:bg-stone-100 hover:text-stone-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stone-400"
          >
            End conversation
          </button>
        )}
      </div>
    </div>
  )
}
