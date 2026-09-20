import { createContext, useCallback, useContext, useLayoutEffect, useRef, useState } from 'react'

const TipContext = createContext(null)

/**
 * A figure in running prose that reveals its evidence on hover, focus or tap:
 * what the data actually says, and what that forced in the agent.
 */
export function Fact({ children, inData, forAgent }) {
  const ctx = useContext(TipContext)
  const ref = useRef(null)
  const open = ctx?.openEl === ref.current && !!ctx?.openEl

  const show = () => ctx?.show(ref.current, { inData, forAgent })
  const hide = () => ctx?.hide()

  return (
    <button
      type="button"
      ref={ref}
      className="mark"
      aria-expanded={open}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      onClick={(e) => {
        e.preventDefault()
        open ? hide() : show()
      }}
    >
      {children}
    </button>
  )
}

/** Wraps a region of prose and hosts the single floating tooltip. */
export function FactProvider({ children }) {
  const [state, setState] = useState(null)
  const [pos, setPos] = useState(null)
  const tipRef = useRef(null)

  const show = useCallback((el, content) => {
    if (!el) return
    setState({ el, ...content })
  }, [])

  const hide = useCallback(() => {
    setState(null)
    setPos(null)
  }, [])

  // Measure after paint, then clamp inside the viewport.
  useLayoutEffect(() => {
    if (!state?.el || !tipRef.current) return
    const place = () => {
      const r = state.el.getBoundingClientRect()
      const t = tipRef.current.getBoundingClientRect()
      const pad = 12
      let left = r.left + r.width / 2 - t.width / 2
      left = Math.max(pad, Math.min(left, window.innerWidth - t.width - pad))
      const below = r.bottom + 10
      const above = r.top - t.height - 10
      let top = below + t.height + pad <= window.innerHeight || above < pad ? below : above
      top = Math.max(pad, Math.min(top, window.innerHeight - t.height - pad))
      setPos({ left: Math.round(left), top: Math.round(top) })
    }
    place()
    const onKey = (e) => e.key === 'Escape' && hide()
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', hide)
    document.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', hide)
      document.removeEventListener('keydown', onKey)
    }
  }, [state, hide])

  return (
    <TipContext.Provider value={{ show, hide, openEl: state?.el }}>
      {children}
      {state && (
        <div
          className="tip"
          role="tooltip"
          ref={tipRef}
          style={{ left: pos?.left ?? -9999, top: pos?.top ?? -9999, visibility: pos ? 'visible' : 'hidden' }}
          onMouseLeave={hide}
        >
          <div className="tip-row">
            <span className="tip-tag data">In the data</span>
            <span className="tip-body">{state.inData}</span>
          </div>
          <div className="tip-row">
            <span className="tip-tag agent">For the agent</span>
            <span className="tip-body dim">{state.forAgent}</span>
          </div>
        </div>
      )}
    </TipContext.Provider>
  )
}
