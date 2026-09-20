import { money } from '../format'

export default function Guidelines({ g }) {
  if (!g) return <div className="panel"><div className="empty">Loading guidelines…</div></div>
  const t = g.thresholds

  const rows = [
    ['Line of business', 'Property', '—', 'Every other line'],
    [
      'Primary risk state',
      `Target: ${t.target_states.join(', ')}`,
      t.acceptable_states.filter((s) => !t.target_states.includes(s)).join(', '),
      'Every other state',
    ],
    [
      'Total insured value',
      `Target ${money(t.tiv_target[0])}–${money(t.tiv_target[1])}`,
      `Acceptable up to ${money(t.tiv_ceiling)}`,
      `Over ${money(t.tiv_ceiling)} is out`,
    ],
    [
      'Total premium',
      `Target ${money(t.premium_target[0])}–${money(t.premium_target[1])}`,
      `Acceptable ${money(t.premium_band[0])}–${money(t.premium_band[1])}`,
      'Outside the band is out',
    ],
    [
      'Building age',
      `Target ${t.building_year_target} or newer`,
      `Acceptable after ${t.building_year_acceptable}`,
      `Pre-${t.building_year_acceptable} is out`,
    ],
    [
      'Construction type',
      '90%+ of insured value in acceptable classes',
      `>50% in: ${t.acceptable_construction.join(', ')}`,
      'Majority of value in combustible construction',
    ],
    [
      '5-year loss history',
      'No claims',
      `Under ${money(t.loss_limit)} incurred`,
      `Over ${money(t.loss_limit)} is out`,
    ],
    ['Submission type', 'Renewal', 'New business', '—'],
    ['5-year loss history', 'No claims', `Under ${money(t.loss_limit)} incurred`, `Over ${money(t.loss_limit)} incurred`],
  ]

  return (
    <div className="panel">
      <p className="lede">
        The 2025 commercial property table, as the agent actually applies it. Weights are served
        from the same objects the scorer uses, so this page cannot drift from the scoring.
      </p>

      <table className="grid" style={{ marginTop: 20 }}>
        <thead>
          <tr>
            <th>Factor</th>
            <th>Weight</th>
            <th>Target</th>
            <th>Acceptable</th>
            <th>Not acceptable</th>
          </tr>
        </thead>
        <tbody>
          {g.factors.map((f) => {
            const row = rows.find((r) => r[0] === f.label) || [f.label, '', '', '']
            return (
              <tr key={f.key}>
                <td style={{ fontWeight: 600 }}>
                  {f.label}
                  {f.hard_stop && (
                    <span className="flag" style={{ marginLeft: 7 }}>
                      hard stop
                    </span>
                  )}
                </td>
                <td className="num">{f.weight}</td>
                <td>{row[1]}</td>
                <td>{row[2]}</td>
                <td>{row[3]}</td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <div className="section">
        <h3>How a score is built</h3>
        <div className="facts">
          <div className="fact">
            <div className="k">Target</div>
            <div className="v">{g.grade_points.target * 100}% of weight</div>
          </div>
          <div className="fact">
            <div className="k">Acceptable</div>
            <div className="v">{g.grade_points.acceptable * 100}% of weight</div>
          </div>
          <div className="fact">
            <div className="k">Unknown</div>
            <div className="v">{g.grade_points.unknown * 100}% of weight</div>
            <div className="n">
              Missing data scores between acceptable and unacceptable rather than at zero —
              penalising an unworked submission as though it were a bad risk would bury every
              genuinely new account in the queue.
            </div>
          </div>
          <div className="fact">
            <div className="k">Unacceptable</div>
            <div className="v">0</div>
          </div>
          <div className="fact">
            <div className="k">Hard stop</div>
            <div className="v">Caps at 25</div>
            <div className="n">
              Capped rather than zeroed, so an out-of-footprint account that is otherwise strong
              stays visible as a broker conversation or a filing question.
            </div>
          </div>
          <div className="fact">
            <div className="k">Weather adjustment</div>
            <div className="v">±5</div>
            <div className="n">
              External severe-weather history breaks ties between comparable risks; it cannot
              overturn the carrier's own table.
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
