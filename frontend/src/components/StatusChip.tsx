import { statusLabel } from '../lib/format'
import type { SkuStatus } from '../types'

const TONES: Record<SkuStatus, string> = {
  TO_ORDER: 'chip-blue',
  NO_ORDER_NEEDED: 'chip-grey',
  HOLDING_NOT_SET: 'chip-red',
  NO_DEMAND_DATA: 'chip-amber',
}

export default function StatusChip({ status, zeroForecast }: { status: SkuStatus; zeroForecast: boolean }) {
  return (
    <span className="chips">
      <span className={`chip ${TONES[status]}`}>{statusLabel(status)}</span>
      {zeroForecast && (
        <span
          className="chip chip-amber"
          title="All 3 forecast months are zero or missing; the order comes from actual sales only"
        >
          Zero forecast
        </span>
      )}
    </span>
  )
}
