import { useState } from 'react'
import AppBar from '@mui/material/AppBar'
import Toolbar from '@mui/material/Toolbar'
import Typography from '@mui/material/Typography'
import Tabs from '@mui/material/Tabs'
import Tab from '@mui/material/Tab'
import Container from '@mui/material/Container'
import Box from '@mui/material/Box'
import SubmitterView from './SubmitterView.jsx'
import ApproverView from './ApproverView.jsx'

export default function App() {
  const [tab, setTab] = useState(0)

  return (
    <>
      <AppBar position="static" color="primary" elevation={1}>
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            ApprovalFlow
          </Typography>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} textColor="inherit" indicatorColor="secondary">
            <Tab label="Submitter" />
            <Tab label="Approver" />
          </Tabs>
        </Toolbar>
      </AppBar>
      <Container maxWidth="md" sx={{ mt: 4, mb: 6 }}>
        <Box hidden={tab !== 0}>
          <SubmitterView />
        </Box>
        <Box hidden={tab !== 1}>
          <ApproverView />
        </Box>
      </Container>
    </>
  )
}
