import type { Flag } from '../types'
import { flagLabel, flagTone } from '../lib/format'

export default function FlagChips({ flags }: { flags: Flag[] }) {
  if (flags.length === 0) return <span className="muted">–</span>
  return (
    <span className="chips">
      {flags.map((f) => (
        <span key={f.code} className={`chip ${flagTone(f.code)}`} title={f.message}>
          {flagLabel(f.code)}
        </span>
      ))}
    </span>
  )
}
