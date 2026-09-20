import { useState } from 'react'
import { askQuestion } from '../api'

const EXAMPLES = [
  'Which open property submissions are in California with clean loss history?',
  'What is our total TIV exposure in flood-tagged locations?',
  'Which broker brings us the most premium, and is any of it out of appetite?',
  'Why were submissions declined, and would our scoring have caught them?',
]

export default function Ask({ enabled }) {
  const [q, setQ] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const submit = async (text) => {
    const question = (text ?? q).trim()
    if (!question || loading) return
    setQ(question)
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      setResult(await askQuestion(question))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const steps = (result?.trace?.steps || []).filter(
    (s) => s.payload || s.result_count !== null,
  )

  return (
    <div className="panel">
      <p className="lede">
        Ask about the book in plain English. The model reads the schema the agent discovered,
        decides which queries answer the question, runs them through the same adaptive runner as
        the rest of the agent, and reads the results before answering. Appetite judgement is
        handed to the deterministic scorer rather than improvised — so scores stay reproducible
        whatever the model does.
      </p>

      {!enabled && (
        <div className="banner warn" style={{ marginTop: 16 }}>
          <b>Needs a key</b>
          <p>
            Set ANTHROPIC_API_KEY in .env and restart the API. The ranked queue and its
            explanations work without one.
          </p>
        </div>
      )}

      <form
        className="askbar"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <input
          id="ask-input"
          className="askinput"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Which submissions should I work first, and why?"
          disabled={!enabled || loading}
          autoComplete="off"
        />
        <button className="btn primary" type="submit" disabled={!enabled || loading || !q.trim()}>
          {loading ? 'Planning…' : 'Ask'}
        </button>
      </form>

      {!result && !loading && (
        <div className="examples">
          {EXAMPLES.map((ex) => (
            <button key={ex} className="example" onClick={() => submit(ex)} disabled={!enabled}>
              {ex}
            </button>
          ))}
        </div>
      )}

      {loading && (
        <div className="loading">
          <span className="spinner" />
          Reading the schema, planning queries, running them…
        </div>
      )}

      {error && (
        <div className="error" style={{ marginTop: 18 }}>
          {error}
        </div>
      )}

      {result && (
        <>
          <div className="section">
            <h3>Answer</h3>
            <div className="note answer">{result.answer}</div>
          </div>

          {steps.length > 0 && (
            <div className="section">
              <h3>
                Queries the model chose · {result.tool_calls} tool{' '}
                {result.tool_calls === 1 ? 'call' : 'calls'} · {result.model}
              </h3>
              {steps.map((s, i) => (
                <div className={`step${s.payload ? ' q' : ''}`} key={i}>
                  <h4>
                    {i + 1}. {s.goal}
                  </h4>
                  {s.payload && <pre className="q">{JSON.stringify(s.payload, null, 1)}</pre>}
                  {s.outcome && (
                    <div className={`out${s.error ? ' err' : ''}`}>→ {s.outcome}</div>
                  )}
                  {s.adaptation && <div className="adapt">adapted: {s.adaptation}</div>}
                </div>
              ))}
            </div>
          )}

          {result.truncated && (
            <div className="banner warn">
              <b>Partial</b>
              <p>The loop hit its query limit, so the answer covers only what it retrieved.</p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
