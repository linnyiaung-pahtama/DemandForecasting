export type ColumnView = 'months' | 'weeks'

const VIEWS: { view: ColumnView; label: string }[] = [
  { view: 'months', label: 'Months' },
  { view: 'weeks', label: 'Weeks' },
]

/** Months | Weeks: one column per plan month, or one per week of each month, for the order plan's orders. */
export default function ColumnSwitch({ view, onChange }: { view: ColumnView; onChange: (view: ColumnView) => void }) {
  return (
    <div className="mode-switch" role="group" aria-label="Order plan columns">
      {VIEWS.map((v) => (
        <button key={v.view} type="button" aria-pressed={view === v.view} onClick={() => onChange(v.view)}>
          {v.label}
        </button>
      ))}
    </div>
  )
}
