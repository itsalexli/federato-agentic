import { useState } from 'react'

/* One step of the loop, rendered as the handoff it actually is.
 *
 * The trace stores a step flat, but its fields come from three different
 * actors: the planner states the goal, rationale and hypothesis; the
 * deterministic executor produces the payload, outcome and any adaptation;
 * the critic returns the verdict. Rendering them in one undifferentiated
 * block is what made the reasoning hard to follow -- you could read what
 * happened but not who decided it. So each lane is labelled, and a lane is
 * omitted when that actor had nothing to do with the step. */

const VERDICT = {
  satisfied: { tone: 'good', label: 'bore out' },
  insufficient: { tone: 'warn', label: 'fell short' },
  contradicted: { tone: 'bad', label: 'contradicted' },
}

/* A plain-English gloss of the query, so the shape of it can be read without
 * parsing JSON. The payload stays one click away for anyone who wants it. */
function summarise(payload) {
  const parts = []
  const keys = (o) => (o && typeof o === 'object' ? Object.keys(o) : [])

  if (payload.resource) parts.push(payload.resource)
  if (payload.where) parts.push(`where ${keys(payload.where).join(', ') || '…'}`)
  if (payload.expand) parts.push(`expand ${describeExpand(payload.expand).join(' · ')}`)
  if (payload.unwind) parts.push(`unwind ${[].concat(payload.unwind).join(', ')}`)
  if (payload.filter) parts.push(`filter ${keys(payload.filter).join(', ')}`)
  if (payload.over) parts.push(`group by ${[].concat(payload.over).join(', ')}`)
  if (payload.select) {
    const n = Array.isArray(payload.select) ? payload.select.length : keys(payload.select).length
    parts.push(`select ${n} field${n === 1 ? '' : 's'}`)
  }
  if (payload.limit) parts.push(`limit ${payload.limit}`)
  return parts
}

/* Expansion routes read as paths -- insured→hq→buildings -- because that is
 * how the planner derived them, and seeing both routes side by side is the
 * point of keeping every minimal route rather than the first one found. */
function describeExpand(expand, prefix = []) {
  const out = []
  for (const [key, value] of Object.entries(expand || {})) {
    const path = [...prefix, key]
    if (value && typeof value === 'object') out.push(...describeExpand(value, path))
    else out.push(path.join('→'))
  }
  return out
}

function Lane({ actor, tone, children }) {
  return (
    <div className={`lane${tone ? ` ${tone}` : ''}`}>
      <span className="lane-actor">{actor}</span>
      <div className="lane-body">{children}</div>
    </div>
  )
}

export default function TraceStep({ step, index }) {
  const [open, setOpen] = useState(false)
  const ran = step.payload || step.outcome
  const verdict = step.verification && VERDICT[step.verification.verdict]
  const summary = step.payload ? summarise(step.payload) : []

  return (
    <div className={`step${step.payload ? ' q' : ''}`}>
      <h4>
        {index + 1}. {step.goal}
        {step.duration_ms > 0 && <span className="step-ms">{step.duration_ms}ms</span>}
      </h4>

      <Lane actor="planner">
        <p className="why">{step.rationale}</p>
        {step.hypothesis && (
          <p className="why hyp">
            <strong>expects </strong>
            {step.hypothesis}
          </p>
        )}
      </Lane>

      {ran && (
        <Lane actor="executor">
          {summary.length > 0 && (
            <button className="qsum" onClick={() => setOpen(!open)} aria-expanded={open}>
              <span className="qsum-caret">{open ? '▾' : '▸'}</span>
              {summary.map((p, i) => (
                <span className="qsum-part" key={i}>
                  {p}
                </span>
              ))}
            </button>
          )}
          {open && step.payload && <pre className="q">{JSON.stringify(step.payload, null, 1)}</pre>}
          {step.outcome && (
            <div className={`out${step.error ? ' err' : ''}`}>
              {step.result_count !== null && step.result_count !== undefined
                ? `→ ${step.outcome}`
                : step.outcome}
            </div>
          )}
          {step.adaptation && (
            <div className="adapt">
              adapted without asking the model: {step.adaptation}
            </div>
          )}
        </Lane>
      )}

      {verdict && (
        <Lane actor="critic" tone={verdict.tone}>
          <div className="out verdict">
            <strong>{verdict.label} — </strong>
            {step.verification.reasoning}
            {step.verification.next_step ? ` Still missing: ${step.verification.next_step}` : ''}
          </div>
        </Lane>
      )}
    </div>
  )
}
