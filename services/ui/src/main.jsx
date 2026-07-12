import React, { useMemo } from 'react'
import ReactDOM from 'react-dom/client'
import CssBaseline from '@mui/material/CssBaseline'
import useMediaQuery from '@mui/material/useMediaQuery'
import { ThemeProvider, createTheme } from '@mui/material/styles'
import App from './App.jsx'

function Root() {
  // Follows the OS/browser dark-light setting automatically, same as Chrome/Edge's own
  // settings pages — no in-app toggle, just prefers-color-scheme.
  const prefersDark = useMediaQuery('(prefers-color-scheme: dark)')

  const theme = useMemo(
    () =>
      createTheme({
        palette: {
          mode: prefersDark ? 'dark' : 'light',
          primary: { main: '#1565c0' },
          secondary: { main: '#00897b' },
        },
        shape: { borderRadius: 12 },
      }),
    [prefersDark],
  )

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <App />
    </ThemeProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
