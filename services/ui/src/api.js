const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const text = await response.text()
  const body = text ? JSON.parse(text) : null
  if (!response.ok) {
    const detail = body && body.detail ? body.detail : response.statusText
    throw new Error(detail)
  }
  return body
}

export const submitInvoice = (invoice) =>
  request('/submit', { method: 'POST', body: JSON.stringify(invoice) })

export const getStatus = (trackingId) => request(`/status/${trackingId}`)

export const listEscalations = () => request('/escalations')

export const decideEscalation = (trackingId, decision) =>
  request(`/escalations/${trackingId}/decide`, { method: 'POST', body: JSON.stringify(decision) })

export const provideInfo = (trackingId, info) =>
  request(`/escalations/${trackingId}/info`, { method: 'POST', body: JSON.stringify({ info }) })
