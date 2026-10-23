import type { Flag, FlagCode } from '../types'
import { flagLabel } from '../lib/format'

const SEVERE: FlagCode[] = ['ORDER_NOW', 'STOCKOUT_RISK']
const WARN: FlagCode[] = [
  'EXCESS',
  'EXPIRY_RISK',
  'LEAD_TIME_EXCEEDS_REORDER',
  'MOQ_EXCEEDS_SHELF_LIFE',
  'MISSING_LEAD_TIME',
]

function tone(code: FlagCode): string {
  if (SEVERE.includes(code)) return 'chip-red'
  if (WARN.includes(code)) return 'chip-amber'
  return 'chip-grey'
}

export default function FlagChips({ flags }: { flags: Flag[] }) {
  if (flags.length === 0) return <span className="muted">–</span>
  return (
    <span className="chips">
      {flags.map((f) => (
        <span key={f.code} className={`chip ${tone(f.code)}`} title={f.message}>
          {flagLabel(f.code)}
        </span>
      ))}
    </span>
  )
}
