import { useState } from 'react'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import CardHeader from '@mui/material/CardHeader'
import Grid from '@mui/material/Grid'
import TextField from '@mui/material/TextField'
import MenuItem from '@mui/material/MenuItem'
import Checkbox from '@mui/material/Checkbox'
import FormControlLabel from '@mui/material/FormControlLabel'
import Button from '@mui/material/Button'
import Alert from '@mui/material/Alert'
import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import Divider from '@mui/material/Divider'
import Typography from '@mui/material/Typography'
import CircularProgress from '@mui/material/CircularProgress'
import { submitInvoice, getStatus, provideInfo } from './api.js'

const CATEGORIES = ['meals', 'travel', 'software', 'hardware', 'other']

const STAGE_COLOR = {
  processing: 'default',
  escalated: 'warning',
  awaiting_info: 'warning',
  approved_pending_payment: 'info',
  paid: 'success',
  payment_failed: 'error',
  rejected: 'error',
}

const emptyForm = {
  submitter: '',
  department: '',
  vendor: '',
  vendorKnown: true,
  invoiceNumber: '',
  currency: 'USD',
  category: 'meals',
  attendees: '',
  description: '',
  quantity: 1,
  unitPrice: '',
  taxAmount: 0,
  receiptPresent: true,
  date: new Date().toISOString().slice(0, 10),
  notes: '',
}

export default function SubmitterView() {
  const [form, setForm] = useState(emptyForm)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)
  const [trackingId, setTrackingId] = useState('')
  const [lookupId, setLookupId] = useState('')
  const [status, setStatus] = useState(null)
  const [statusError, setStatusError] = useState(null)
  const [statusLoading, setStatusLoading] = useState(false)
  const [infoText, setInfoText] = useState('')

  const total = (Number(form.quantity) || 0) * (Number(form.unitPrice) || 0) + (Number(form.taxAmount) || 0)

  const update = (field) => (event) => {
    const value = event.target.type === 'checkbox' ? event.target.checked : event.target.value
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setSubmitting(true)
    setSubmitError(null)
    try {
      const payload = {
        id: `INV-${Date.now()}`,
        submitter: form.submitter,
        department: form.department,
        vendor: form.vendor,
        vendorKnown: form.vendorKnown,
        invoiceNumber: form.invoiceNumber,
        currency: form.currency,
        category: form.category,
        attendees: form.attendees ? Number(form.attendees) : null,
        lineItems: [
          { description: form.description, quantity: Number(form.quantity), unitPrice: Number(form.unitPrice) },
        ],
        taxAmount: Number(form.taxAmount) || 0,
        total,
        receiptPresent: form.receiptPresent,
        date: form.date,
        notes: form.notes,
      }
      const result = await submitInvoice(payload)
      setTrackingId(result.tracking_id)
      setLookupId(result.tracking_id)
      setForm(emptyForm)
    } catch (err) {
      setSubmitError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const handleLookup = async () => {
    if (!lookupId) return
    setStatusLoading(true)
    setStatusError(null)
    try {
      setStatus(await getStatus(lookupId))
    } catch (err) {
      setStatusError(err.message)
      setStatus(null)
    } finally {
      setStatusLoading(false)
    }
  }

  const handleProvideInfo = async () => {
    if (!lookupId || !infoText) return
    try {
      await provideInfo(lookupId, { business_justification: infoText })
      setInfoText('')
      await handleLookup()
    } catch (err) {
      setStatusError(err.message)
    }
  }

  return (
    <Stack spacing={3}>
      <Card elevation={2}>
        <CardHeader
          title="Submit an expense"
          subheader="You get a tracking id immediately; processing happens in the background"
        />
        <CardContent>
          <form onSubmit={handleSubmit}>
            <Grid container spacing={2}>
              <Grid item xs={12} sm={6}>
                <TextField label="Your email" fullWidth required value={form.submitter} onChange={update('submitter')} />
              </Grid>
              <Grid item xs={12} sm={6}>
                <TextField label="Department" fullWidth required value={form.department} onChange={update('department')} />
              </Grid>
              <Grid item xs={12} sm={6}>
                <TextField label="Vendor" fullWidth required value={form.vendor} onChange={update('vendor')} />
              </Grid>
              <Grid item xs={12} sm={6}>
                <TextField label="Invoice number" fullWidth required value={form.invoiceNumber} onChange={update('invoiceNumber')} />
              </Grid>
              <Grid item xs={6} sm={3}>
                <TextField label="Currency" fullWidth value={form.currency} onChange={update('currency')} />
              </Grid>
              <Grid item xs={6} sm={3}>
                <TextField select label="Category" fullWidth value={form.category} onChange={update('category')}>
                  {CATEGORIES.map((c) => (
                    <MenuItem key={c} value={c}>{c}</MenuItem>
                  ))}
                </TextField>
              </Grid>
              <Grid item xs={6} sm={3}>
                <TextField label="Attendees" type="number" fullWidth value={form.attendees} onChange={update('attendees')} />
              </Grid>
              <Grid item xs={6} sm={3}>
                <TextField
                  label="Date"
                  type="date"
                  fullWidth
                  value={form.date}
                  onChange={update('date')}
                  InputLabelProps={{ shrink: true }}
                />
              </Grid>

              <Grid item xs={12}>
                <Divider textAlign="left">Line item</Divider>
              </Grid>
              <Grid item xs={12} sm={6}>
                <TextField label="Description" fullWidth required value={form.description} onChange={update('description')} />
              </Grid>
              <Grid item xs={6} sm={2}>
                <TextField label="Qty" type="number" fullWidth value={form.quantity} onChange={update('quantity')} />
              </Grid>
              <Grid item xs={6} sm={2}>
                <TextField label="Unit price" type="number" fullWidth required value={form.unitPrice} onChange={update('unitPrice')} />
              </Grid>
              <Grid item xs={6} sm={2}>
                <TextField label="Tax" type="number" fullWidth value={form.taxAmount} onChange={update('taxAmount')} />
              </Grid>

              <Grid item xs={12} sm={6}>
                <FormControlLabel
                  control={<Checkbox checked={form.vendorKnown} onChange={update('vendorKnown')} />}
                  label="Vendor is known/approved"
                />
              </Grid>
              <Grid item xs={12} sm={6}>
                <FormControlLabel
                  control={<Checkbox checked={form.receiptPresent} onChange={update('receiptPresent')} />}
                  label="Receipt attached"
                />
              </Grid>
              <Grid item xs={12}>
                <TextField label="Notes" fullWidth multiline minRows={2} value={form.notes} onChange={update('notes')} />
              </Grid>
              <Grid item xs={12}>
                <Typography variant="body2" color="text.secondary">
                  Total (auto-calculated): {total.toFixed(2)} {form.currency}
                </Typography>
              </Grid>
              <Grid item xs={12}>
                <Button type="submit" variant="contained" disabled={submitting}>
                  {submitting ? <CircularProgress size={20} /> : 'Submit'}
                </Button>
              </Grid>
            </Grid>
          </form>
          {submitError && <Alert severity="error" sx={{ mt: 2 }}>{submitError}</Alert>}
          {trackingId && (
            <Alert severity="success" sx={{ mt: 2 }}>
              Submitted. Tracking id: <strong>{trackingId}</strong>
            </Alert>
          )}
        </CardContent>
      </Card>

      <Card elevation={2}>
        <CardHeader title="Check status" subheader="Plain-language reason for the outcome" />
        <CardContent>
          <Stack direction="row" spacing={2} alignItems="center">
            <TextField label="Tracking id" fullWidth value={lookupId} onChange={(e) => setLookupId(e.target.value)} />
            <Button variant="outlined" onClick={handleLookup} disabled={statusLoading}>
              {statusLoading ? <CircularProgress size={20} /> : 'Check'}
            </Button>
          </Stack>
          {statusError && <Alert severity="error" sx={{ mt: 2 }}>{statusError}</Alert>}
          {status && (
            <Stack spacing={1} sx={{ mt: 2 }}>
              <Chip label={status.stage} color={STAGE_COLOR[status.stage] || 'default'} sx={{ width: 'fit-content' }} />
              <Typography>{status.message}</Typography>
              {status.reason && (
                <Typography variant="body2" color="text.secondary">
                  Reason: {status.reason}
                </Typography>
              )}
              {status.stage === 'awaiting_info' && (
                <Stack direction="row" spacing={2} sx={{ mt: 1 }}>
                  <TextField
                    label="Business justification"
                    fullWidth
                    value={infoText}
                    onChange={(e) => setInfoText(e.target.value)}
                  />
                  <Button variant="contained" onClick={handleProvideInfo}>Send</Button>
                </Stack>
              )}
            </Stack>
          )}
        </CardContent>
      </Card>
    </Stack>
  )
}
