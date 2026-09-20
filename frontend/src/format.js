export const money = (v) => {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(1)}B`
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`
  if (Math.abs(n) >= 1e3) return `$${Math.round(n / 1e3)}K`
  return `$${n.toLocaleString()}`
}

export const num = (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString())
export const pct = (v) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`)
export const title = (s) => (s || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

export const tone = (score) =>
  score >= 70 ? 'var(--good)' : score >= 45 ? 'var(--warn)' : 'var(--bad)'

export const date = (s) => {
  if (!s) return '—'
  const d = new Date(s)
  return Number.isNaN(d.getTime())
    ? s
    : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

// The backend keeps its strings ASCII so the CLI stays portable; the browser
// can render the real thing.
export const dash = (s) => (s || '').replace(/ -- /g, ' \u2014 ').replace(/--/g, '\u2014')
