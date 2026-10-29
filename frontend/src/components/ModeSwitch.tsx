import { MODE_LABEL, type PlanMode } from '../lib/mode'

const MODES: PlanMode[] = ['plan', 'forecast']

/** Order plan | Order demand forecast: which plan every order figure on the page comes from. */
export default function ModeSwitch({ mode, onChange }: { mode: PlanMode; onChange: (mode: PlanMode) => void }) {
  return (
    <div className="mode-switch" role="group" aria-label="Order figures">
      {MODES.map((m) => (
        <button key={m} type="button" aria-pressed={mode === m} onClick={() => onChange(m)}>
          {MODE_LABEL[m]}
        </button>
      ))}
    </div>
  )
}
