import { money, title, tone } from '../format'

export default function QueueCard({ row, selected, onSelect }) {
  return (
    <button
      className={`card${selected ? ' on' : ''}${row.disqualified ? '' : ' hot'}`}
      style={{ '--tone': tone(row.score) }}
      onClick={() => onSelect(row.submission_id)}
    >
      <div className="card-top">
        <span className="rank">#{row.rank}</span>
        <span className="score">{row.score}</span>
        <span className="card-name">{row.account_name || row.submission_number}</span>
        <span className={`pill ${row.recommendation}`}>{title(row.recommendation)}</span>
      </div>

      <div className="card-meta">
        <span>{row.line_of_business}</span>
        <span className="dot">·</span>
        <span>{row.status}</span>
        <span className="dot">·</span>
        <span>{row.primary_risk_state || '??'}</span>
        <span className="dot">·</span>
        <span>TIV {money(row.tiv)}</span>
        {row.duplicate_account && <span className="flag">repeat of #{row.duplicate_of_rank}</span>}
      </div>

      <div className="meter">
        <i style={{ width: `${row.score}%` }} />
      </div>
    </button>
  )
}
