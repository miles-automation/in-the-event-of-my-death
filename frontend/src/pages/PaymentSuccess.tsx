import { useEffect, useState, useCallback } from 'react'
import { useSearchParams, Link } from 'react-router-dom'

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

  const [status, setStatus] = useState<
    'loading' | 'pending' | 'success' | 'error' | 'already_retrieved'
  >('loading')
  const [token, setToken] = useState<string | null>(null)
  const [tierInfo, setTierInfo] = useState<{ maxFileSize: number; maxExpiryDays: number } | null>(
    null,
  )
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

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
        setToken(data.token)
        setTierInfo({
          maxFileSize: data.max_file_size_bytes || 50_000_000,
          maxExpiryDays: data.max_expiry_days || 1825,
        })
        setStatus('success')
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
  }, [invoiceId])

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

  const copyToken = async () => {
    if (!token) return
    try {
      await navigator.clipboard.writeText(token)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback for older browsers
      const textarea = document.createElement('textarea')
      textarea.value = token
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const formatFileSize = (bytes: number) => {
    return `${Math.round(bytes / 1_000_000)}MB`
  }

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

      {status === 'success' && token && (
        <>
          <h1>Payment Complete!</h1>
          <p>Thank you for your purchase. Here is your premium token:</p>

          <div className="token-display">
            <code className="token-value">{token}</code>
            <button onClick={copyToken} className="button secondary copy-button">
              {copied ? 'Copied!' : 'Copy Token'}
            </button>
          </div>

          <div className="token-warning">
            <strong>Important:</strong> Save this token now. It can only be displayed once and
            cannot be recovered.
          </div>

          {tierInfo && (
            <div className="tier-benefits">
              <h3>Your Premium Benefits</h3>
              <ul>
                <li>Up to {formatFileSize(tierInfo.maxFileSize)} file attachments</li>
                <li>{Math.round(tierInfo.maxExpiryDays / 365)}-year maximum expiry</li>
              </ul>
            </div>
          )}

          <div className="next-steps">
            <h3>How to Use Your Token</h3>
            <ol>
              <li>
                Go to the <Link to="/">home page</Link> to create a secret
              </li>
              <li>When prompted, enter your premium token</li>
              <li>Your premium limits will be applied to that secret</li>
            </ol>
          </div>

          <Link to="/" className="button primary">
            Create a Premium Secret
          </Link>
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
