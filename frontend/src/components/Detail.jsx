import { dash, date, money, num, pct, title, tone } from '../format'

const Factor = ({ f }) => (
  <div className="factor">
    <div className="fl">
      <i className={`tick ${f.grade}`} />
      {f.label}
    </div>
    <div>
      <div className="fd">{dash(f.detail)}</div>
      <div className="fbar">
        <i className={f.grade} style={{ width: `${(f.points / f.max_points) * 100}%` }} />
      </div>
    </div>
    <div className="fp">
      {f.points.toFixed(1)}/{f.max_points}
    </div>
  </div>
)

const Fact = ({ k, v, n }) => (
  <div className="fact">
    <div className="k">{k}</div>
    <div className="v">{v}</div>
    {n && <div className="n">{n}</div>}
  </div>
)

export default function Detail({ row }) {
  if (!row) {
    return (
      <div className="detail">
        <div className="empty">Select a submission to see its scorecard.</div>
      </div>
    )
  }

  const color = tone(row.score)
  const e = row.enrichment

  return (
    <div className="detail" style={{ '--tone': color }}>
      <div className="detail-head">
        <div>
          <h2>{row.account_name || 'Unnamed account'}</h2>
          <div className="sub">
            {row.submission_number} · {row.line_of_business} · {row.status} · received{' '}
            {date(row.received_date)} · target effective {date(row.target_effective_date)}
          </div>
          <div className="sub">
            {row.broker_name && <>Broker {row.broker_name} ({row.broker_tier}) · </>}
            {row.underwriter_name ? `Underwriter ${row.underwriter_name}` : 'Unassigned'}
          </div>
        </div>
        <div className="bigscore">
          <div className="n">{row.score}</div>
          <div className="l">
            of 100 · {pct(row.confidence)} confidence
          </div>
          <div style={{ marginTop: 8 }}>
            <span className={`pill ${row.recommendation}`}>{title(row.recommendation)}</span>
          </div>
        </div>
      </div>

      {row.disqualified && (
        <div className="banner stop" style={{ marginTop: 18 }}>
          <b>Hard stop</b>
          {row.disqualifiers.map((d, i) => (
            <p key={i}>{dash(d)}</p>
          ))}
        </div>
      )}

      {row.contradictions?.length > 0 && (
        <div className="banner warn" style={{ marginTop: row.disqualified ? 0 : 18 }}>
          <b>Read with care</b>
          {row.contradictions.map((c, i) => (
            <p key={i}>{dash(c)}</p>
          ))}
        </div>
      )}

      <div className="section">
        <h3>Underwriter note</h3>
        <div className="note">
          {dash(row.explanation)}
          <span className="src">
            {row.explanation_source === 'llm'
              ? 'Written by the language model from the scorecard below.'
              : 'Generated deterministically from the scorecard below.'}
          </span>
        </div>
      </div>

      <div className="section">
        <h3>Appetite scorecard</h3>
        {row.factors.map((f) => (
          <Factor key={f.key} f={f} />
        ))}
        {e && (
          <div className="factor">
            <div className="fl">
              <i className="tick acceptable" />
              Weather history
            </div>
            <div>
              <div className="fd">
                {dash(e.summary)} Base score {row.base_score} → {row.score}.
              </div>
            </div>
            <div className="fp">
              {e.adjustment > 0 ? '+' : ''}
              {e.adjustment.toFixed(1)}
            </div>
          </div>
        )}
      </div>

      <div className="section">
        <h3>Exposure</h3>
        <div className="facts">
          <Fact k="Primary risk state" v={row.primary_risk_state || '—'} />
          <Fact
            k="Total insured value"
            v={money(row.tiv)}
            n={row.building_count ? `${row.building_count} buildings on record` : 'no buildings found'}
          />
          <Fact k="Premium" v={money(row.premium)} n={dash(row.premium_basis) || 'no prior term on this line'} />
          <Fact k="Requested limit" v={money(row.requested_limit)} />
          <Fact k="Oldest building" v={row.oldest_building_year || '—'} />
          <Fact
            k="5-year incurred loss"
            v={money(row.five_year_loss)}
            n={dash(row.five_year_loss_basis)}
          />
        </div>
      </div>

      <div className="section">
        <h3>Account</h3>
        <div className="facts">
          <Fact k="Entity type" v={row.entity_type || '—'} />
          <Fact k="Annual revenue" v={money(row.annual_revenue)} />
          <Fact k="Employees" v={num(row.employee_count)} />
          <Fact k="Founded" v={row.year_founded || '—'} />
          <Fact k="NAICS" v={row.naics_code || '—'} />
          <Fact
            k="Prior policies"
            v={num(row.prior_policy_count)}
            n={row.prior_policy_lines?.join(', ') || 'none on file'}
          />
        </div>
      </div>

      {row.construction_mix && Object.keys(row.construction_mix).length > 0 && (
        <div className="section">
          <h3>Construction mix by insured value</h3>
          <table className="grid">
            <tbody>
              {Object.entries(row.construction_mix)
                .sort((a, b) => b[1] - a[1])
                .map(([type, value]) => {
                  const total = Object.values(row.construction_mix).reduce((a, b) => a + b, 0)
                  return (
                    <tr key={type}>
                      <td>{type}</td>
                      <td className="num">{money(value)}</td>
                      <td style={{ width: 120 }}>
                        <div className="sharebar">
                          <i style={{ width: `${(value / total) * 100}%` }} />
                        </div>
                      </td>
                      <td className="num" style={{ width: 52 }}>
                        {Math.round((value / total) * 100)}%
                      </td>
                    </tr>
                  )
                })}
            </tbody>
          </table>
        </div>
      )}

      {row.locations?.length > 0 && (
        <div className="section">
          <h3>Locations, largest first</h3>
          <table className="grid">
            <thead>
              <tr>
                <th>Site</th>
                <th>City</th>
                <th>State</th>
                <th>TIV</th>
                <th>Hazards</th>
              </tr>
            </thead>
            <tbody>
              {row.locations.slice(0, 8).map((l) => (
                <tr key={l.id}>
                  <td>{l.name || `#${l.id}`}</td>
                  <td>{l.city || '—'}</td>
                  <td>{l.state || '—'}</td>
                  <td className="num">{money(l.tiv)}</td>
                  <td>
                    <div className="tags">
                      {(l.hazard_tags || []).map((t) => (
                        <span className="tag" key={t}>
                          {t}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
