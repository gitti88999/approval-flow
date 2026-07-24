const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const TOKEN_STORAGE_KEY = 'approvalflow_auth'

export function getSession() {
  const raw = localStorage.getItem(TOKEN_STORAGE_KEY)
  return raw ? JSON.parse(raw) : null
}

export function clearSession() {
  localStorage.removeItem(TOKEN_STORAGE_KEY)
}

function setSession(session) {
  localStorage.setItem(TOKEN_STORAGE_KEY, JSON.stringify(session))
}

async function request(path, options = {}) {
  const session = getSession()
  const headers = { 'Content-Type': 'application/json' }
  if (session?.access_token) {
    headers.Authorization = `Bearer ${session.access_token}`
  }

  const response = await fetch(`${API_BASE}${path}`, { headers, ...options })
  const text = await response.text()
  const body = text ? JSON.parse(text) : null
  if (!response.ok) {
    const detail = body && body.detail ? body.detail : response.statusText
    throw new Error(detail)
  }
  return body
}

export async function register(username, password, role) {
  const response = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, role }),
  })
  const body = await response.json()
  if (!response.ok) {
    throw new Error(body?.detail || 'Registration failed')
  }
  return body
}

export async function login(username, password) {
  const response = await fetch(`${API_BASE}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const body = await response.json()
  if (!response.ok) {
    throw new Error(body?.detail || 'Login failed')
  }
  const session = { username, role: body.role, access_token: body.access_token }
  setSession(session)
  return session
}

export const submitInvoice = (invoice) =>
  request('/submit', { method: 'POST', body: JSON.stringify(invoice) })

export const getStatus = (trackingId) => request(`/status/${trackingId}`)

export const listEscalations = () => request('/escalations')

export const listAllEscalations = () => request('/escalations/all')

export const decideEscalation = (trackingId, decision) =>
  request(`/escalations/${trackingId}/decide`, { method: 'POST', body: JSON.stringify(decision) })

export const provideInfo = (trackingId, info) =>
  request(`/escalations/${trackingId}/info`, { method: 'POST', body: JSON.stringify({ info }) })

export const listPendingUsers = () => request('/auth/pending-users')

export const decidePendingUser = (username, approve) =>
  request(`/auth/users/${username}/decide`, { method: 'POST', body: JSON.stringify({ approve }) })
