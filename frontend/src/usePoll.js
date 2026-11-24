import { useEffect, useRef } from 'react'

/** Calls fn now and every `ms` while the tab is visible. Pass ms=null to stop polling. */
export function usePoll(fn, ms, deps = []) {
  const saved = useRef(fn)
  saved.current = fn
  useEffect(() => {
    saved.current()
    if (!ms) return undefined
    const id = setInterval(() => { if (!document.hidden) saved.current() }, ms)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ms, ...deps])
}
