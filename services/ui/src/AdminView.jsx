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
import { listPendingUsers, decidePendingUser } from './api.js'

export default function AdminView() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [busyUsername, setBusyUsername] = useState(null)

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
  }, [])

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

  return (
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
  )
}
