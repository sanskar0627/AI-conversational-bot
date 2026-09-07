import { useEffect, useState } from 'react'
import type { BookingSnapshot, MemorySnapshot, SlotInfo } from '../lib/types'

type BookingCardProps = {
  booking: BookingSnapshot | null
  memory: MemorySnapshot | null
  slots: SlotInfo[]
  busy: boolean
  disabled: boolean
  onBook: (slotId: string, name: string, phone: string) => void
}

function profileValue(memory: MemorySnapshot | null, key: string): string {
  const field = memory?.profile[key]
  if (!field || field.value === null || field.value === undefined) return ''
  return String(field.value)
}

function slotLabel(slots: SlotInfo[], slotId: string | null): string {
  if (!slotId) return '—'
  return slots.find((slot) => slot.slot_id === slotId)?.label ?? slotId
}

export function BookingCard({ booking, memory, slots, busy, disabled, onBook }: BookingCardProps) {
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')

  useEffect(() => {
    const knownName = profileValue(memory, 'name')
    if (knownName) setName(knownName)
  }, [memory])

  useEffect(() => {
    // The memory snapshot masks phone digits; only prefill while it looks complete.
    const knownPhone = profileValue(memory, 'phone')
    if (knownPhone && !knownPhone.includes('X')) setPhone(knownPhone)
  }, [memory])

  const status = booking?.status ?? 'none'
  const confirmed = status === 'confirmed'
  const failed = status === 'failed'
  const alternatives = booking?.alternatives ?? []
  const pickerSlots = failed && alternatives.length > 0 ? alternatives : slots

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-stone-400">
          Site visit
        </span>
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${
            confirmed
              ? 'bg-emerald-50 text-emerald-800 ring-emerald-100'
              : failed
                ? 'bg-red-50 text-red-800 ring-red-100'
                : 'bg-stone-50 text-stone-600 ring-stone-200'
          }`}
        >
          {confirmed ? 'Confirmed' : failed ? 'Failed' : 'Not booked'}
        </span>
      </div>

      {confirmed && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-sm text-emerald-900">
          <p className="font-semibold">Visit confirmed</p>
          <p className="mt-0.5">
            Slot: <span className="font-medium">{slotLabel(slots, booking?.slot ?? null)}</span>
          </p>
          {booking?.confirmation_id && (
            <p className="mt-0.5">
              Confirmation ID:{' '}
              <span className="font-mono font-medium">{booking.confirmation_id}</span>
            </p>
          )}
        </div>
      )}

      {failed && booking?.reason && (
        <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-800">
          <p className="font-semibold">Booking failed</p>
          <p className="mt-0.5">{booking.reason}</p>
          {alternatives.length > 0 && (
            <p className="mt-1 text-xs text-red-700">
              Pick one of the suggested alternatives below to retry.
            </p>
          )}
        </div>
      )}

      {!confirmed && (
        <>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <div>
              <label htmlFor="booking-name" className="mb-1 block text-xs text-stone-500">
                Name
              </label>
              <input
                id="booking-name"
                type="text"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Your name"
                className="w-full rounded-md border border-stone-300 px-2.5 py-1.5 text-sm focus:border-indigo-900 focus:outline-none focus:ring-2 focus:ring-indigo-900/20"
              />
            </div>
            <div>
              <label htmlFor="booking-phone" className="mb-1 block text-xs text-stone-500">
                Phone
              </label>
              <input
                id="booking-phone"
                type="tel"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                placeholder="10-digit mobile"
                className="w-full rounded-md border border-stone-300 px-2.5 py-1.5 text-sm focus:border-indigo-900 focus:outline-none focus:ring-2 focus:ring-indigo-900/20"
              />
            </div>
          </div>

          <div>
            <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-stone-400">
              {failed && alternatives.length > 0 ? 'Alternative slots' : 'Available slots'}
            </h3>
            {pickerSlots.length === 0 ? (
              <p className="text-sm text-stone-500">Loading slots…</p>
            ) : (
              <ul className="flex flex-wrap gap-1.5">
                {pickerSlots.map((slot) => (
                  <li key={slot.slot_id}>
                    <button
                      type="button"
                      disabled={disabled || busy || !slot.available || name.trim().length < 2 || phone.trim().length < 10}
                      onClick={() => onBook(slot.slot_id, name.trim(), phone.trim())}
                      className="rounded-full border border-indigo-200 bg-white px-3 py-1.5 text-xs font-medium text-indigo-900 hover:bg-indigo-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-900 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {slot.label}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {name.trim().length < 2 || phone.trim().length < 10 ? (
              <p className="mt-1.5 text-xs text-stone-400">
                Enter your name and phone number to book a slot.
              </p>
            ) : null}
          </div>
        </>
      )}

      {busy && <p className="text-xs text-stone-400">Contacting the booking desk…</p>}
    </div>
  )
}
