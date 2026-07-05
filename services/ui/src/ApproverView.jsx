import { useEffect, useState } from 'react'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import CardHeader from '@mui/material/CardHeader'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import Chip from '@mui/material/Chip'
import Button from '@mui/material/Button'
import TextField from '@mui/material/TextField'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import Divider from '@mui/material/Divider'
import { listEscalations, decideEscalation } from './api.js'

export default function ApproverView() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [approver, setApprover] = useState('')
  const [notes, setNotes] = useState({})
  const [busyId, setBusyId] = useState(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      setItems(await listEscalations())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const act = async (trackingId, action) => {
    if (!approver) {
      setError('Enter your name/email as approver first')
      return
    }
    setBusyId(trackingId)
    setError(null)
    try {
      await decideEscalation(trackingId, { action, approver, notes: notes[trackingId] || '' })
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <Stack spacing={3}>
      <Card elevation={2}>
        <CardHeader title="Approver queue" subheader="Only the items the system escalated" />
        <CardContent>
          <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
            <TextField label="Approver (your email)" value={approver} onChange={(e) => setApprover(e.target.value)} />
            <Button variant="outlined" onClick={load} disabled={loading}>
              {loading ? <CircularProgress size={20} /> : 'Refresh'}
            </Button>
          </Stack>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
          {items.length === 0 && !loading && (
            <Typography color="text.secondary">Nothing waiting for review.</Typography>
          )}
          <Stack spacing={2}>
            {items.map((item) => (
              <Card key={item.tracking_id} variant="outlined">
                <CardContent>
                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Typography variant="subtitle1">
                      {item.invoice?.id} — {item.invoice?.vendor}
                    </Typography>
                    <Chip
                      label={item.status}
                      size="small"
                      color={item.status === 'info_requested' ? 'warning' : 'default'}
                    />
                  </Stack>
                  <Typography variant="body2" color="text.secondary">
                    Amount: {item.invoice?.total} {item.invoice?.currency} · Confidence: {item.confidence}
                  </Typography>
                  <Typography variant="body2" sx={{ mt: 1 }}>{item.reason}</Typography>
                  <Divider sx={{ my: 1 }} />
                  <TextField
                    label="Notes"
                    size="small"
                    fullWidth
                    value={notes[item.tracking_id] || ''}
                    onChange={(e) => setNotes((prev) => ({ ...prev, [item.tracking_id]: e.target.value }))}
                    sx={{ mb: 1 }}
                  />
                  <Stack direction="row" spacing={1}>
                    <Button
                      size="small"
                      variant="contained"
                      color="success"
                      disabled={busyId === item.tracking_id}
                      onClick={() => act(item.tracking_id, 'approve')}
                    >
                      Approve
                    </Button>
                    <Button
                      size="small"
                      variant="contained"
                      color="error"
                      disabled={busyId === item.tracking_id}
                      onClick={() => act(item.tracking_id, 'reject')}
                    >
                      Reject
                    </Button>
                    <Button
                      size="small"
                      variant="outlined"
                      disabled={busyId === item.tracking_id}
                      onClick={() => act(item.tracking_id, 'request_info')}
                    >
                      Request info
                    </Button>
                  </Stack>
                </CardContent>
              </Card>
            ))}
          </Stack>
        </CardContent>
      </Card>
    </Stack>
  )
}
