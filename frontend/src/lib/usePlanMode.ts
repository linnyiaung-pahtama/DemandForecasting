import { useSearchParams } from 'react-router-dom'
import { readMode, type PlanMode } from './mode'

/** The plan mode kept in the URL (`?mode=forecast`), so it carries over between pages and survives a reload. */
export function usePlanMode(): [PlanMode, (mode: PlanMode) => void] {
  const [params, setParams] = useSearchParams()
  function setMode(mode: PlanMode) {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (mode === 'forecast') next.set('mode', 'forecast')
        else next.delete('mode')
        return next
      },
      { replace: true },
    )
  }
  return [readMode(params), setMode]
}
