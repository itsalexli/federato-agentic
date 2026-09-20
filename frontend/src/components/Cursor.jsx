import { useEffect, useRef, useState } from 'react'

/**
 * A two-part pointer: a precise dot that tracks exactly, and a ring that
 * trails behind it. The ring is what the command palette grows out of, so its
 * position is published on window for the palette to read at open time.
 *
 * Disabled entirely for touch, for coarse pointers, and when the viewer has
 * asked for reduced motion — in all three the native cursor is the right call.
 */
export default function Cursor({ armed, open }) {
  const dot = useRef(null)
  const ring = useRef(null)
  const [on, setOn] = useState(false)

  // `armed` and `open` are toggled imperatively rather than baked into the
  // JSX className. Mixing the two rewrites the whole attribute on every React
  // render and silently wipes the classes the pointer handler just set — which
  // is how the ring kept its teal while the dot had already gone brown.
  useEffect(() => {
    ring.current?.classList.toggle('armed', !!armed)
  }, [armed, on])

  useEffect(() => {
    ring.current?.classList.toggle('gone', !!open)
  }, [open, on])

  useEffect(() => {
    const fine = window.matchMedia('(pointer: fine)').matches
    const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (!fine || calm) return

    setOn(true)
    document.documentElement.classList.add('has-cursor')

    let x = window.innerWidth / 2
    let y = window.innerHeight / 2
    let rx = x
    let ry = y
    let raf = 0

    const move = (e) => {
      x = e.clientX
      y = e.clientY
      window.__cursor = { x, y }
      if (dot.current) dot.current.style.transform = `translate3d(${x}px, ${y}px, 0)`

      // Interactive targets get a wider ring, so the pointer reads as a state.
      const hot = e.target?.closest?.(
        'button, a, input, select, textarea, [role="button"], .card, .mark, .tab',
      )
      ring.current?.classList.toggle('hot', !!hot)

      // Brown over the cream band, teal over the dark one, so the pointer
      // always has contrast against whatever it is sitting on.
      const onLight = !!e.target?.closest?.('.band-light')
      ring.current?.classList.toggle('on-light', onLight)
      dot.current?.classList.toggle('on-light', onLight)
    }

    const tick = () => {
      rx += (x - rx) * 0.18
      ry += (y - ry) * 0.18
      if (ring.current) ring.current.style.transform = `translate3d(${rx}px, ${ry}px, 0)`
      window.__cursorRing = { x: rx, y: ry }
      raf = requestAnimationFrame(tick)
    }

    const down = () => ring.current?.classList.add('down')
    const up = () => ring.current?.classList.remove('down')
    const leave = () => document.documentElement.classList.add('cursor-out')
    const enter = () => document.documentElement.classList.remove('cursor-out')

    window.addEventListener('mousemove', move)
    window.addEventListener('mousedown', down)
    window.addEventListener('mouseup', up)
    document.addEventListener('mouseleave', leave)
    document.addEventListener('mouseenter', enter)
    raf = requestAnimationFrame(tick)

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mousedown', down)
      window.removeEventListener('mouseup', up)
      document.removeEventListener('mouseleave', leave)
      document.removeEventListener('mouseenter', enter)
      document.documentElement.classList.remove('has-cursor', 'cursor-out')
    }
  }, [])

  if (!on) return null

  return (
    <>
      <div className="cursor-ring" ref={ring} aria-hidden="true">
        <span className="cursor-hint">Tab again to ask</span>
      </div>
      <div className="cursor-dot" ref={dot} aria-hidden="true" />
    </>
  )
}
