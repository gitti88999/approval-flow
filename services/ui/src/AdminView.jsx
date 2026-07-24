import { useEffect, useState } from 'react'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import CardHeader from '@mui/material/CardHeader'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import Chip from '@mui/material/Chip'
import Button from '@mui/material/Button'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import FormControl from '@mui/material/FormControl'
import InputLabel from '@mui/material/InputLabel'
import Select from '@mui/material/Select'
import MenuItem from '@mui/material/MenuItem'
import Divider from '@mui/material/Divider'
import { listPendingUsers, decidePendingUser, listAllEscalations, decideEscalation, getSession } from './api.js'

export default function AdminView() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [busyUsername, setBusyUsername] = useState(null)
  const [escalations, setEscalations] = useState([])
  const [loadingEsc, setLoadingEsc] = useState(false)
  const [busyTracking, setBusyTracking] = useState(null)
  const [divisionFilter, setDivisionFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [sourceFilter, setSourceFilter] = useState('all')

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      setUsers(await listPendingUsers())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    loadEscalations()
  }, [])

  const loadEscalations = async () => {
    setLoadingEsc(true)
    try {
      setEscalations(await listAllEscalations())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoadingEsc(false)
    }
  }

  const divisions = Array.from(new Set(escalations.map((e) => e.invoice?.department).filter(Boolean)))

  const matchesSource = (e) => {
    if (sourceFilter === 'all') return true
    const isHuman = Boolean(e.approver)
    const isAuto = !isHuman && e.recommendation === 'approve'
    return sourceFilter === 'human' ? isHuman : isAuto
  }

  const matchesStatus = (e) => {
    if (statusFilter === 'all') return true
    if (statusFilter === 'approved') return e.status === 'approved'
    if (statusFilter === 'rejected') return e.status === 'rejected'
    if (statusFilter === 'pending') return e.status === 'pending'
    if (statusFilter === 'info_requested') return e.status === 'info_requested'
    return true
  }

  const filteredEscalations = escalations.filter((e) => {
    if (divisionFilter !== 'all' && e.invoice?.department !== divisionFilter) return false
    if (!matchesSource(e)) return false
    if (!matchesStatus(e)) return false
    return true
  })

  const stats = {
    approved: escalations.filter((e) => e.status === 'approved').length,
    rejected: escalations.filter((e) => e.status === 'rejected').length,
    auto: escalations.filter((e) => !e.approver && e.recommendation === 'approve').length,
    human: escalations.filter((e) => Boolean(e.approver)).length,
  }

  const act = async (username, approve) => {
    setBusyUsername(username)
    setError(null)
    try {
      await decidePendingUser(username, approve)
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusyUsername(null)
    }
  }

  const decide = async (trackingId, action) => {
    setBusyTracking(trackingId)
    setError(null)
    try {
      const session = getSession()
      await decideEscalation(trackingId, { action, approver: session?.username || 'admin', notes: '' })
      await loadEscalations()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusyTracking(null)
    }
  }

  return (
    <>
      <Card elevation={2}>
      <CardHeader title="Pending accounts" subheader="Submitter/approver signups awaiting approval" />
      <CardContent>
        <Stack direction="row" spacing={2} sx={{ mb: 2 }}>
          <Button variant="outlined" onClick={load} disabled={loading}>
            {loading ? <CircularProgress size={20} /> : 'Refresh'}
          </Button>
        </Stack>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        {users.length === 0 && !loading && (
          <Typography color="text.secondary">Nothing waiting for approval.</Typography>
        )}
        <Stack spacing={2}>
          {users.map((u) => (
            <Card key={u.username} variant="outlined">
              <CardContent>
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Typography variant="subtitle1">{u.username}</Typography>
                  <Chip label={`requested: ${u.role}`} size="small" />
                </Stack>
                <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                  <Button
                    size="small"
                    variant="contained"
                    color="success"
                    disabled={busyUsername === u.username}
                    onClick={() => act(u.username, true)}
                  >
                    Approve
                  </Button>
                  <Button
                    size="small"
                    variant="contained"
                    color="error"
                    disabled={busyUsername === u.username}
                    onClick={() => act(u.username, false)}
                  >
                    Reject
                  </Button>
                </Stack>
              </CardContent>
            </Card>
          ))}
        </Stack>
      </CardContent>
    </Card>
    <Card elevation={2} sx={{ mt: 2 }}>
      <CardHeader title="Escalations" subheader="All requests and decisions" />
      <CardContent>
        <Stack direction="row" spacing={2} sx={{ mb: 2 }} alignItems="center">
          <Button variant="outlined" onClick={loadEscalations} disabled={loadingEsc}>
            {loadingEsc ? <CircularProgress size={20} /> : 'Refresh'}
          </Button>
          <Divider orientation="vertical" flexItem sx={{ mx: 1 }} />
          
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel id="status-label">Status</InputLabel>
            <Select labelId="status-label" value={statusFilter} label="Status" onChange={(e) => setStatusFilter(e.target.value)}>
              <MenuItem value="all">All</MenuItem>
              <MenuItem value="pending">Pending</MenuItem>
              <MenuItem value="approved">Approved</MenuItem>
              <MenuItem value="rejected">Rejected</MenuItem>
              <MenuItem value="info_requested">Info Requested</MenuItem>
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel id="source-label">Source</InputLabel>
            <Select labelId="source-label" value={sourceFilter} label="Source" onChange={(e) => setSourceFilter(e.target.value)}>
              <MenuItem value="all">All</MenuItem>
              <MenuItem value="auto">Auto</MenuItem>
              <MenuItem value="human">Human</MenuItem>
            </Select>
          </FormControl>
          <Divider orientation="vertical" flexItem sx={{ mx: 1 }} />
          <Chip label={`Approved: ${stats.approved}`} size="small" sx={{ mr: 1 }} />
          <Chip label={`Rejected: ${stats.rejected}`} size="small" sx={{ mr: 1 }} />
          <Chip label={`Auto: ${stats.auto}`} size="small" sx={{ mr: 1 }} />
          <Chip label={`Human: ${stats.human}`} size="small" />
        </Stack>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        {filteredEscalations.length === 0 && !loadingEsc && (
          <Typography color="text.secondary">No escalations found for the selected filters.</Typography>
        )}
        <Stack spacing={2}>
          {(() => {
            const groups = {}
            filteredEscalations.forEach((e) => {
              const div = e.invoice?.department || 'Unassigned'
              if (!groups[div]) groups[div] = []
              groups[div].push(e)
            })
            return Object.keys(groups).map((div) => (
              <div key={div}>
                <Typography variant="h6" sx={{ mt: 1, mb: 1 }}>{div}</Typography>
                <Stack spacing={2}>
                  {groups[div].map((e) => (
                    <Card key={`${div}-${e.tracking_id}`} variant="outlined">
                      <CardContent>
                        <Stack direction="row" justifyContent="space-between" alignItems="center">
                          <Typography variant="subtitle1">{e.tracking_id}</Typography>
                          <Stack direction="row" spacing={1} alignItems="center">
                            <Chip label={`status: ${e.status || 'n/a'}`} size="small" />
                            <Chip label={e.approver ? 'human' : e.recommendation === 'approve' ? 'auto' : 'agent'} size="small" />
                            {e.invoice?.department && <Chip label={e.invoice.department} size="small" />}
                          </Stack>
                        </Stack>
                        <Typography variant="body2" sx={{ mt: 1 }}>Recommendation: {e.recommendation} (confidence: {e.confidence})</Typography>
                        <Typography variant="body2" sx={{ mt: 1 }}>Reason: {e.reason}</Typography>
                        {e.approver && <Typography variant="body2" sx={{ mt: 1 }}>By: {e.approver} — {e.approver_notes}</Typography>}
                        <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                          {['pending', 'info_requested'].includes(e.status) && (
                            <>
                              <Button size="small" variant="contained" color="success" disabled={busyTracking === e.tracking_id} onClick={() => decide(e.tracking_id, 'approve')}>Approve</Button>
                              <Button size="small" variant="contained" color="error" disabled={busyTracking === e.tracking_id} onClick={() => decide(e.tracking_id, 'reject')}>Reject</Button>
                              <Button size="small" variant="outlined" disabled={busyTracking === e.tracking_id} onClick={() => decide(e.tracking_id, 'request_info')}>Request Info</Button>
                            </>
                          )}
                        </Stack>
                      </CardContent>
                    </Card>
                  ))}
                </Stack>
              </div>
            ))
          })()}
        </Stack>
      </CardContent>
      </Card>
    </>
  )
}
