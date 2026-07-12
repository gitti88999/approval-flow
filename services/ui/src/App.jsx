import { useState } from 'react'
import AppBar from '@mui/material/AppBar'
import Toolbar from '@mui/material/Toolbar'
import Typography from '@mui/material/Typography'
import Tabs from '@mui/material/Tabs'
import Tab from '@mui/material/Tab'
import Container from '@mui/material/Container'
import Chip from '@mui/material/Chip'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import SubmitterView from './SubmitterView.jsx'
import ApproverView from './ApproverView.jsx'
import AdminView from './AdminView.jsx'
import Login from './Login.jsx'
import { getSession, clearSession } from './api.js'

function initialTabForRole(role) {
  if (role === 'admin') return 2
  if (role === 'approver') return 1
  return 0
}

export default function App() {
  const [session, setSession] = useState(getSession())
  const [tab, setTab] = useState(initialTabForRole(session?.role))

  if (!session) {
    return (
      <Login
        onLoggedIn={(newSession) => {
          setSession(newSession)
          setTab(initialTabForRole(newSession.role))
        }}
      />
    )
  }

  const handleLogout = () => {
    clearSession()
    setSession(null)
  }

  const canSubmit = session.role === 'submitter' || session.role === 'approver' || session.role === 'admin'
  const canApprove = session.role === 'approver' || session.role === 'admin'
  const canAdmin = session.role === 'admin'

  return (
    <>
      <AppBar position="static" color="primary" elevation={1}>
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            ApprovalFlow
          </Typography>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} textColor="inherit" indicatorColor="secondary">
            {canSubmit && <Tab label="Submitter" value={0} />}
            {canApprove && <Tab label="Approver" value={1} />}
            {canAdmin && <Tab label="Admin" value={2} />}
          </Tabs>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ ml: 2 }}>
            <Chip label={`${session.username} (${session.role})`} size="small" color="secondary" />
            <Button color="inherit" size="small" onClick={handleLogout}>
              Logout
            </Button>
          </Stack>
        </Toolbar>
      </AppBar>
      <Container maxWidth="md" sx={{ mt: 4, mb: 6 }}>
        {/* Only the active tab is mounted, so a role without access to another tab never
            fires its data-loading effect (e.g. a submitter never calls GET /escalations). */}
        {tab === 0 && canSubmit && <SubmitterView />}
        {tab === 1 && canApprove && <ApproverView />}
        {tab === 2 && canAdmin && <AdminView />}
      </Container>
    </>
  )
}
