const VERDICT_COLOR = {
  satisfied: 'var(--good, #2e7d5b)',
  insufficient: 'var(--warn, #9a6b12)',
  contradicted: 'var(--bad, #b3352f)',
}

export default function Trace({ trace, bare = false }) {
  return (
    <div className={bare ? '' : 'panel'}>
      <p className="lede">
        Every query the agent ran, in order, with the reasoning that produced it. The schema is
        discovered first, the data behind each appetite rule is located in it, and the queries are
        derived from those routes rather than written by hand — so this list is a record of the
        agent's decisions, not a log of fixed calls. Where a step states what it expected to
        find, a separate verifier judged the result against that expectation and its verdict is
        shown underneath.
      </p>

      <div style={{ marginTop: 22 }}>
        {trace.steps.map((s, i) => (
          <div className={`step${s.payload ? ' q' : ''}`} key={i}>
            <h4>
              {i + 1}. {s.goal}
              {s.duration_ms > 0 && (
                <span style={{ color: 'var(--ink-3)', fontWeight: 400, fontSize: 11.5, fontFamily: 'var(--mono)' }}>
                  {'  '}
                  {s.duration_ms}ms
                </span>
              )}
            </h4>
            <p className="why">{s.rationale}</p>
            {s.hypothesis && (
              <p className="why">
                <strong>expected: </strong>
                {s.hypothesis}
              </p>
            )}
            {s.payload && <pre className="q">{JSON.stringify(s.payload, null, 1)}</pre>}
            {s.outcome && (
              <div className={`out${s.error ? ' err' : ''}`}>
                {s.result_count !== null && s.result_count !== undefined
                  ? `→ ${s.outcome}`
                  : s.outcome}
              </div>
            )}
            {s.verification && (
              <div className="out" style={{ color: VERDICT_COLOR[s.verification.verdict] }}>
                <strong>verified [{s.verification.verdict}] </strong>
                {s.verification.reasoning}
                {s.verification.next_step ? ` Still missing: ${s.verification.next_step}` : ''}
              </div>
            )}
            {s.adaptation && <div className="adapt">adapted: {s.adaptation}</div>}
          </div>
        ))}
      </div>

      {trace.notes?.length > 0 && (
        <div className="notes">
          {trace.notes.map((n, i) => (
            <div key={i}>{n}</div>
          ))}
        </div>
      )}
    </div>
  )
}
