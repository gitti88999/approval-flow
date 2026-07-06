import { useState } from 'react'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import CardHeader from '@mui/material/CardHeader'
import TextField from '@mui/material/TextField'
import MenuItem from '@mui/material/MenuItem'
import Button from '@mui/material/Button'
import Alert from '@mui/material/Alert'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import CircularProgress from '@mui/material/CircularProgress'
import Container from '@mui/material/Container'
import Link from '@mui/material/Link'
import { login, register } from './api.js'

const ROLES = ['submitter', 'approver', 'admin']

export default function Login({ onLoggedIn }) {
  const [mode, setMode] = useState('login') // 'login' | 'register'
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('submitter')
  const [error, setError] = useState(null)
  const [info, setInfo] = useState(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (event) => {
    event.preventDefault()
    setLoading(true)
    setError(null)
    setInfo(null)
    try {
      if (mode === 'login') {
        const session = await login(username, password)
        onLoggedIn(session)
      } else {
        await register(username, password, role)
        setInfo('Account created — an admin must approve it before you can sign in.')
        setMode('login')
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Container maxWidth="xs" sx={{ mt: 10 }}>
      <Card elevation={3}>
        <CardHeader
          title="ApprovalFlow"
          subheader={mode === 'login' ? 'Sign in to continue' : 'Create an account'}
        />
        <CardContent>
          <form onSubmit={handleSubmit}>
            <Stack spacing={2}>
              <TextField
                label="Username"
                fullWidth
                required
                autoFocus
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
              <TextField
                label="Password"
                type="password"
                fullWidth
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              {mode === 'register' && (
                <TextField select label="Role" fullWidth value={role} onChange={(e) => setRole(e.target.value)}>
                  {ROLES.map((r) => (
                    <MenuItem key={r} value={r}>{r}</MenuItem>
                  ))}
                </TextField>
              )}
              {error && <Alert severity="error">{error}</Alert>}
              {info && <Alert severity="success">{info}</Alert>}
              <Button type="submit" variant="contained" disabled={loading}>
                {loading ? <CircularProgress size={20} /> : mode === 'login' ? 'Sign in' : 'Register'}
              </Button>
            </Stack>
          </form>
          <Typography variant="body2" sx={{ mt: 2 }}>
            {mode === 'login' ? (
              <>
                No account?{' '}
                <Link component="button" type="button" onClick={() => { setMode('register'); setError(null) }}>
                  Register one
                </Link>
              </>
            ) : (
              <>
                Already have an account?{' '}
                <Link component="button" type="button" onClick={() => { setMode('login'); setError(null) }}>
                  Sign in
                </Link>
              </>
            )}
          </Typography>
        </CardContent>
      </Card>
    </Container>
  )
}
