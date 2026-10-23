import { useState } from 'react'
import type { ChangeEvent } from 'react'

/**
 * A weeks input that always resolves to a whole number from 1 to 52: while the user types,
 * empty or invalid text keeps the last valid value; on blur the text snaps back to it.
 */
export function useWeeksInput(initial: number) {
  const [weeks, setWeeks] = useState(initial)
  const [text, setText] = useState(String(initial))

  const inputProps = {
    value: text,
    onChange: (e: ChangeEvent<HTMLInputElement>) => {
      const next = e.target.value
      setText(next)
      const n = Number(next)
      if (next.trim() !== '' && Number.isInteger(n) && n >= 1 && n <= 52) setWeeks(n)
    },
    onBlur: () => setText(String(weeks)),
  }

  return { weeks, inputProps }
}
