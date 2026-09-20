import { money } from '../format'

export default function Portfolio({ portfolio, submissions }) {
  const states = portfolio.by_state || []
  if (!states.length) {
    return <div className="panel">
      <div className="empty">{portfolio.unavailable || 'No portfolio data available.'}</div>
    </div>
  }

  const max = Math.max(...states.map((s) => s.share))
  // Which states the queue would add to, so concentration can be read against demand.
  const demand = {}
  submissions.forEach((s) => {
    if (s.primary_risk_state) demand[s.primary_risk_state] = (demand[s.primary_risk_state] || 0) + 1
  })

  return (
    <div className="panel">
      <p className="lede">
        Bound and active premium by state, against how many submissions in the current queue would
        add to each one. Appetite is not only about the submission — an account in a state the book
        is already heavy in is worth less than the same account where the carrier has room. A policy
        with exposure in several states is counted under each of them.
      </p>

      <table className="grid" style={{ marginTop: 20 }}>
        <thead>
          <tr>
            <th>State</th>
            <th>Policies</th>
            <th>Accounts</th>
            <th>Premium</th>
            <th>Share of book</th>
            <th />
            <th>In this queue</th>
          </tr>
        </thead>
        <tbody>
          {states.map((s) => (
            <tr key={s.state}>
              <td style={{ fontWeight: 600 }}>{s.state || '—'}</td>
              <td className="num">{s.policies}</td>
              <td className="num">{s.accounts ?? '—'}</td>
              <td className="num">{money(s.premium)}</td>
              <td className="num">{(s.share * 100).toFixed(1)}%</td>
              <td style={{ width: 160 }}>
                <div className="sharebar">
                  <i style={{ width: `${(s.share / max) * 100}%` }} />
                </div>
              </td>
              <td className="num">{demand[s.state] ? `+${demand[s.state]}` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {portfolio.server_side_grouping === false && (
        <div className="notes" style={{ marginTop: 18 }}>
          <div>
            The API's <code>over</code> stage did not collapse groups server-side on this
            deployment, so this rollup was recomputed client-side with premium counted once per
            policy rather than once per unwound exposure unit.
          </div>
        </div>
      )}
    </div>
  )
}
