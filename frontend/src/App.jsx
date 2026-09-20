import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchGuidelines, fetchHealth, fetchTriage } from './api'
import { pct, title } from './format'
import Ask from './components/Ask'
import Cursor from './components/Cursor'
import Dataset from './components/Dataset'
import Detail from './components/Detail'
import Guidelines from './components/Guidelines'
import Palette from './components/Palette'
import Portfolio from './components/Portfolio'
import QueueCard from './components/QueueCard'
import Sheet from './components/Sheet'
import Trace from './components/Trace'

const OPEN = ['received', 'cleared', 'quoted']
const ALL = [...OPEN, 'bound', 'declined', 'lost']

const SCOPES = {
  open: { label: 'Open queue', statuses: OPEN },
  all: { label: 'Every submission', statuses: ALL },
}

const TABS = ['Queue', 'Ask', 'Portfolio', 'Guidelines', 'Dataset']

// Two Tab presses inside this window summons the palette. Short enough that
// ordinary tabbing through controls does not trip it.
const DOUBLE_TAB_MS = 350

export default function App() {
  const [scope, setScope] = useState('open')
  const [lob, setLob] = useState('')
  const [tab, setTab] = useState('Queue')
  const [data, setData] = useState(null)
  const [guides, setGuides] = useState(null)
  const [health, setHealth] = useState(null)
  const [selected, setSelected] = useState(null)
  const [showTrace, setShowTrace] = useState(false)
  const [palette, setPalette] = useState(null)   // null = closed, else {x, y}
  const [armed, setArmed] = useState(false)
  const lastTab = useRef(0)
  const disarm = useRef(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = async (refresh = false) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetchTriage({ statuses: SCOPES[scope].statuses, lob, refresh })
      setData(res)
      setSelected(res.submissions[0]?.submission_id ?? null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, lob])

  useEffect(() => {
    fetchGuidelines().then(setGuides).catch(() => {})
    fetchHealth().then(setHealth).catch(() => {})
  }, [])

  const openPalette = useCallback(() => {
    const at = window.__cursorRing || window.__cursor || {
      x: window.innerWidth / 2,
      y: window.innerHeight / 2,
    }
    setArmed(false)
    setPalette(at)
  }, [])

  // Double-Tab to summon, Cmd/Ctrl+K as the conventional alternative.
  // A single Tab is never swallowed, so keyboard navigation still works.
  useEffect(() => {
    const onKey = (e) => {
      if ((e.key === 'k' || e.key === 'K') && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        palette ? setPalette(null) : openPalette()
        return
      }
      if (e.key !== 'Tab' || e.metaKey || e.ctrlKey || e.altKey) return
      if (palette) return

      const now = Date.now()
      if (now - lastTab.current < DOUBLE_TAB_MS) {
        // Only the second press is swallowed; focus stays where the first put it.
        e.preventDefault()
        lastTab.current = 0
        clearTimeout(disarm.current)
        openPalette()
        return
      }
      lastTab.current = now
      setArmed(true)
      clearTimeout(disarm.current)
      disarm.current = setTimeout(() => setArmed(false), DOUBLE_TAB_MS)
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      clearTimeout(disarm.current)
    }
  }, [palette, openPalette])

  const lines = useMemo(() => {
    if (!data) return []
    return [...new Set(data.submissions.map((s) => s.line_of_business))].sort()
  }, [data])

  const current = data?.submissions.find((s) => s.submission_id === selected) || null
  const stats = data?.stats

  return (
    <div className="app">
      <Cursor armed={armed} open={!!palette} />

      {/* Hero: identity and controls, over the aerial field plate. */}
      <div className="band band-hero">
        <div className="band-inner">
      <div className="masthead">
        <div>
          <h1>Underwriting Agent</h1>
          <div className="sub">
            Scores, ranks and explains a commercial submission queue against the 2025 property
            appetite guidelines.{' '}
            <span className="masthead-kbd">
              <kbd>Tab</kbd>
              <kbd>Tab</kbd> to ask
            </span>
          </div>
        </div>

        <div className="controls">
          <select className="select" value={scope} onChange={(e) => setScope(e.target.value)}>
            {Object.entries(SCOPES).map(([k, v]) => (
              <option key={k} value={k}>
                {v.label}
              </option>
            ))}
          </select>
          <select className="select" value={lob} onChange={(e) => setLob(e.target.value)}>
            <option value="">All lines</option>
            {lines.map((l) => (
              <option key={l} value={l}>
                {title(l)}
              </option>
            ))}
          </select>
          <button className="btn primary" onClick={() => load(true)} disabled={loading}>
            {loading ? 'Running…' : 'Re-run agent'}
          </button>
        </div>
      </div>

        </div>
      </div>

      {/* A distinct section for the run's figures and the navigation.
          Its bottom rule runs the full width of the screen. */}
      <div className="band band-stats">
        <div className="band-inner">
      {stats && (
        <div className="stats">
          <div className="stat">
            <div className="k">Submissions</div>
            <div className="v">{stats.submission_count}</div>
          </div>
          <div className="stat">
            <div className="k">In appetite</div>
            <div className="v" style={{ color: 'var(--good)' }}>
              {stats.in_appetite}
            </div>
          </div>
          <div className="stat">
            <div className="k">Hard stops</div>
            <div className="v" style={{ color: 'var(--bad)' }}>
              {stats.disqualified}
            </div>
          </div>
          <div className="stat">
            <div className="k">Mean score</div>
            <div className="v">
              {stats.mean_score}
              <small> /100</small>
            </div>
          </div>
          <div className="stat">
            <div className="k">Confidence</div>
            <div className="v">{pct(stats.mean_confidence)}</div>
          </div>
          <div className="stat">
            <div className="k">API queries</div>
            <div className="v">{stats.api_queries}</div>
          </div>
          <div className="stat">
            <div className="k">Run time</div>
            <div className="v">
              {(stats.elapsed_ms / 1000).toFixed(1)}
              <small>s</small>
            </div>
          </div>
          <div className="stat">
            <div className="k">Enriched</div>
            <div className="v">{stats.enriched}</div>
          </div>
        </div>
      )}

      <div className="tabrow">
        <div className="tabs">
          {TABS.map((t) => (
            <button key={t} className={`tab${tab === t ? ' on' : ''}`} onClick={() => setTab(t)}>
              {t}
            </button>
          ))}
        </div>
        <button
          className="helpbtn"
          onClick={() => setShowTrace(true)}
          disabled={!data}
          title="How the agent reached this ranking"
          aria-label="How the agent reached this ranking"
        >
          ?
        </button>
      </div>
        </div>
      </div>

      {/* Light band: everything below the rule. */}
      <div className="band band-light">
        <div className="band-inner">
      {error && (
        <div className="error">
          Could not reach the agent.
          <code>{error}</code>
          <div style={{ marginTop: 10 }}>
            <button className="btn" onClick={() => load(true)}>
              Retry
            </button>
          </div>
        </div>
      )}

      {loading && !data && tab !== 'Ask' && tab !== 'Dataset' && (
        <div className="loading">
          <span className="spinner" />
          Discovering schema, planning queries, scoring the queue…
        </div>
      )}

      {data && tab === 'Queue' && (
        <div className="split">
          <div className="queue">
            {data.submissions.length === 0 && <div className="empty">No submissions match.</div>}
            {data.submissions.map((row) => (
              <QueueCard
                key={row.submission_id}
                row={row}
                selected={row.submission_id === selected}
                onSelect={setSelected}
              />
            ))}
          </div>
          <Detail row={current} />
        </div>
      )}

      {tab === 'Ask' && <Ask enabled={!!health?.llm_explanations} />}
      {tab === 'Dataset' && <Dataset />}
      {data && tab === 'Portfolio' && (
        <Portfolio portfolio={data.portfolio} submissions={data.submissions} />
      )}
      {tab === 'Guidelines' && <Guidelines g={guides} />}
        </div>
      </div>

      <Palette
        open={!!palette}
        origin={palette}
        enabled={!!health?.llm_explanations}
        context={{ tab, submission_id: selected, statuses: SCOPES[scope].statuses }}
        onClose={() => setPalette(null)}
      />

      {showTrace && data && (
        <Sheet title="How the agent reached this ranking" onClose={() => setShowTrace(false)}>
          <Trace trace={data.trace} bare />
        </Sheet>
      )}
    </div>
  )
}
