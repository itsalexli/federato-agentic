const call = async (path) => {
  const res = await fetch(path)
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body.detail) detail = body.detail
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail)
  }
  return res.json()
}

export const fetchTriage = ({ statuses, lob, refresh }) => {
  const p = new URLSearchParams()
  ;(statuses || []).forEach((s) => p.append('status', s))
  if (lob) p.set('line_of_business', lob)
  if (refresh) p.set('refresh', 'true')
  return call(`/api/triage?${p}`)
}

export const fetchGuidelines = () => call('/api/guidelines')
export const fetchHealth = () => call('/api/health')

export const askQuestion = async (question) => {
  const res = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body.detail) detail = body.detail
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail)
  }
  return res.json()
}
