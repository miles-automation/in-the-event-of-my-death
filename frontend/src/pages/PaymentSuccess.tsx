import { useEffect, useState, useCallback } from 'react'
import { useSearchParams, Link, useNavigate } from 'react-router-dom'

interface TokenResponse {
  status: 'pending' | 'success' | 'already_retrieved'
  message?: string
  token?: string
  tier?: string
  max_file_size_bytes?: number
  max_expiry_days?: number
}

export default function PaymentSuccess() {
  const [searchParams] = useSearchParams()
  const invoiceId = searchParams.get('invoiceId')
  const navigate = useNavigate()

  const [status, setStatus] = useState<
    'loading' | 'pending' | 'success' | 'error' | 'already_retrieved'
  >('loading')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    document.title = 'Payment Complete | In The Event Of My Death'
  }, [])

  const fetchToken = useCallback(async () => {
    if (!invoiceId) {
      setStatus('error')
      setError('No invoice ID provided')
      return
    }

    try {
      const response = await fetch(
        `/api/v1/payment-token?invoice_id=${encodeURIComponent(invoiceId)}`,
      )
      const data: TokenResponse = await response.json()

      if (data.status === 'success' && data.token) {
        // Redirect to home with token - user can create secret immediately
        navigate(`/?token=${encodeURIComponent(data.token)}`, { replace: true })
      } else if (data.status === 'pending') {
        setStatus('pending')
      } else if (data.status === 'already_retrieved') {
        setStatus('already_retrieved')
      } else {
        setStatus('error')
        setError(data.message || 'Unknown error')
      }
    } catch {
      setStatus('error')
      setError('Failed to retrieve token. Please try again.')
    }
  }, [invoiceId, navigate])

  // Initial fetch and polling for pending status
  useEffect(() => {
    fetchToken()

    // Poll every 3 seconds while pending
    const interval = setInterval(() => {
      if (status === 'pending' || status === 'loading') {
        fetchToken()
      }
    }, 3000)

    return () => clearInterval(interval)
  }, [fetchToken, status])

  if (!invoiceId) {
    return (
      <div className="payment-success">
        <h1>Payment Error</h1>
        <p>No invoice ID was provided. If you completed a payment, please contact support.</p>
        <Link to="/pricing" className="button secondary">
          Back to Pricing
        </Link>
      </div>
    )
  }

  return (
    <div className="payment-success">
      {status === 'loading' && (
        <>
          <h1>Checking Payment...</h1>
          <p>Please wait while we verify your payment.</p>
          <div className="loading-spinner" aria-label="Loading" />
        </>
      )}

      {status === 'pending' && (
        <>
          <h1>Payment Processing</h1>
          <p>Your payment is being confirmed on the Bitcoin network.</p>
          <p>This page will update automatically. Please wait...</p>
          <div className="loading-spinner" aria-label="Waiting for confirmation" />
        </>
      )}

      {status === 'already_retrieved' && (
        <>
          <h1>Token Already Retrieved</h1>
          <p>This payment token has already been retrieved.</p>
          <p>
            If you saved your token, you can use it when creating a secret. If you lost it, the
            token cannot be recovered.
          </p>
          <Link to="/" className="button secondary">
            Go to Home
          </Link>
        </>
      )}

      {status === 'error' && (
        <>
          <h1>Something Went Wrong</h1>
          <p>{error}</p>
          <p>
            If you believe your payment was successful, please{' '}
            <Link to="/feedback">contact us</Link> with your invoice ID: <code>{invoiceId}</code>
          </p>
          <Link to="/pricing" className="button secondary">
            Back to Pricing
          </Link>
        </>
      )}
    </div>
  )
}
