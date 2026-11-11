const MOTION_EVENT = 'bartender:motion'

export function emitMotion(kind, detail = {}) {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(MOTION_EVENT, {
    detail: { kind, ...detail },
  }))
}

export function onMotion(listener) {
  if (typeof window === 'undefined') return () => {}
  window.addEventListener(MOTION_EVENT, listener)
  return () => window.removeEventListener(MOTION_EVENT, listener)
}
