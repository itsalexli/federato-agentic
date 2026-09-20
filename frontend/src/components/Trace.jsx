import TraceStep from './TraceStep'

/* The legend is load-bearing, not decoration. Three actors produce this trace
 * and they carry different authority: only the planner is a model choosing
 * freely, the executor is deterministic, and the critic exists precisely
 * because a planner grading its own hypothesis grades it generously. A reader
 * who cannot tell them apart cannot judge how much to trust any given line. */
const ROLES = [
  ['planner', 'A model. Decides what to ask and states what it expects to find.'],
  ['executor', 'Deterministic code, no tokens. Validates, repairs bad paths, broadens empty results.'],
  ['critic', 'A separate call. Judges the result against the hypothesis the planner stated.'],
]

export default function Trace({ trace, bare = false }) {
  const queries = trace.steps.filter((s) => s.payload).length
  const adapted = trace.steps.filter((s) => s.adaptation).length
  const verdicts = trace.steps.filter((s) => s.verification).length

  return (
    <div className={bare ? '' : 'panel'}>
      <p className="lede">
        Every query the agent ran, in order, with the reasoning that produced it. The schema is
        discovered first, the data behind each appetite rule is located in it, and the queries are
        derived from those routes rather than written by hand — so this list is a record of the
        agent's decisions, not a log of fixed calls.
      </p>

      <div className="trace-legend">
        {ROLES.map(([actor, what]) => (
          <div className="trace-role" key={actor}>
            <span className="lane-actor">{actor}</span>
            <p>{what}</p>
          </div>
        ))}
      </div>

      <div className="trace-tally">
        {queries} quer{queries === 1 ? 'y' : 'ies'}
        {adapted > 0 && <> · {adapted} adapted by the executor</>}
        {verdicts > 0 && <> · {verdicts} checked by the critic</>}
        {trace.elapsed_ms ? <> · {(trace.elapsed_ms / 1000).toFixed(1)}s</> : null}
      </div>

      <div className="trace-steps">
        {trace.steps.map((s, i) => (
          <TraceStep step={s} index={i} key={i} />
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
