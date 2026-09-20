import { useEffect, useLayoutEffect, useRef, useState } from 'react'

const W = 400
const SEED = 30 // matches .cursor-ring, so the ring appears to become the box
const CHIPS = ['Why this score?', 'Which queries?', 'Rule or model?']

/**
 * The cursor ring opens into this. It is centred on the pointer and the box
 * itself animates — width, height and corner radius from a 30px circle to the
 * full panel — so the ring reads as becoming the border rather than a separate
 * panel scaling up over the page.
 */
export default function Palette({ open, origin, context, enabled, onClose }) {
  const [q, setQ] = useState('')
  const [thread, setThread] = useState([])
  const [loading, setLoading] = useState(false)
  const [h, setH] = useState(null)
  const [morphing, setMorphing] = useState(false)
  const panel = useRef(null)
  const inner = useRef(null)
  const inputRef = useRef(null)
  const endRef = useRef(null)
  const returnTo = useRef(null)
  const anchor = useRef(null)
  const started = useRef(false)

  // Freeze the point it grew from, so later growth expands around it.
  if (open && !anchor.current) {
    anchor.current = {
      x: origin?.x ?? window.innerWidth / 2,
      y: origin?.y ?? window.innerHeight / 2,
    }
  }

  // Track the content's natural height: it drives the morph target and lets
  // the box grow smoothly as the conversation does.
  useLayoutEffect(() => {
    if (!open) {
      setH(null)
      setMorphing(false)
      started.current = false
      anchor.current = null
      return
    }
    const el = inner.current
    if (!el) return
    const measure = () => setH(el.offsetHeight)
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [open])

  // Kick the morph exactly once, the first time a real height is known.
  // The flag is set in an effect, never during render: React double-invokes
  // render in development, and a ref mutated there is read back already set.
  useLayoutEffect(() => {
    if (open && h != null && !started.current) {
      started.current = true
      setMorphing(true)
    }
  }, [open, h])

  useEffect(() => {
    if (!open) return
    returnTo.current = document.activeElement
    const t = setTimeout(() => inputRef.current?.focus(), 260)
    const onKey = (e) => e.key === 'Escape' && (e.preventDefault(), onClose())
    document.addEventListener('keydown', onKey)
    return () => {
      clearTimeout(t)
      document.removeEventListener('keydown', onKey)
      returnTo.current?.focus?.()
    }
  }, [open, onClose])

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [thread, loading])

  const send = async (text) => {
    const question = (text ?? q).trim()
    if (!question || loading || !enabled) return
    setQ('')
    setThread((t) => [...t, { role: 'user', text: question }])
    setLoading(true)
    try {
      const res = await fetch('/api/how', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, ...context }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(body.detail || `${res.status} ${res.statusText}`)
      setThread((t) => [...t, { role: 'agent', text: body.answer }])
    } catch (err) {
      setThread((t) => [...t, { role: 'error', text: err.message }])
    } finally {
      setLoading(false)
    }
  }

  if (!open) return null

  const a = anchor.current
  const ready = h != null

  // Centred on the pointer, then nudged inside the viewport if it would spill.
  const pad = 14
  const height = h ?? SEED
  const left = Math.max(pad, Math.min(a.x - W / 2, window.innerWidth - W - pad))
  const top = Math.max(pad, Math.min(a.y - height / 2, window.innerHeight - height - pad))

  return (
    <div className="palette-catch" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className={`palette glass${morphing ? ' morph' : ''}`}
        onAnimationEnd={(e) => e.animationName.startsWith('morph') && setMorphing(false)}
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label="Ask about this run"
        style={{
          left,
          top,
          width: W,
          height: ready ? height : SEED,
          '--w': `${W}px`,
          '--h': `${height}px`,
          // Where the ring sat, so the box can grow outward from that point
          // rather than unfurling from one edge.
          '--x0': `${a.x - SEED / 2}px`,
          '--y0': `${a.y - SEED / 2}px`,
          '--x1': `${left}px`,
          '--y1': `${top}px`,
          visibility: ready ? 'visible' : 'hidden',
        }}
      >
        <div className="palette-inner" ref={inner}>
          {(thread.length > 0 || loading) && (
            <div className="palette-thread">
              {thread.map((m, i) => (
                <div key={i} className={`bubble ${m.role}`}>
                  {m.text}
                </div>
              ))}
              {loading && (
                <div className="bubble agent thinking">
                  <span className="dots">
                    <i />
                    <i />
                    <i />
                  </span>
                </div>
              )}
              <div ref={endRef} />
            </div>
          )}

          <form
            className="palette-bar"
            onSubmit={(e) => {
              e.preventDefault()
              send()
            }}
          >
            <input
              id="palette-input"
              ref={inputRef}
              className="palette-input"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={enabled ? 'Ask about this run' : 'Needs ANTHROPIC_API_KEY'}
              disabled={!enabled || loading}
              autoComplete="off"
            />
            <button
              className="palette-send"
              type="submit"
              disabled={!enabled || loading || !q.trim()}
            >
              ↵
            </button>
          </form>

          {enabled && thread.length === 0 && !loading && (
            <div className="palette-chips">
              {CHIPS.map((c) => (
                <button key={c} className="chip" onClick={() => send(c)}>
                  {c}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
