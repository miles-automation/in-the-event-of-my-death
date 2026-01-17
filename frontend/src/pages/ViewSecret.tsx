import { useState, useEffect, useCallback } from 'react'
import { extractFromFragment } from '../utils/urlFragments'
import { getSecretStatus, retrieveSecret } from '../services/api'
import { decryptBytes } from '../services/crypto'
import { decodeSecretPayload } from '../services/secretPayload'

type State =
  | { type: 'loading' }
  | { type: 'missing_params' }
  | { type: 'pending'; unlockAt: Date; expiresAt?: Date }
  | { type: 'ready' }
  | { type: 'retrieving' }
  | {
      type: 'decrypted'
      text: string
      attachments: { name: string; type: string; size: number; url: string }[]
    }
  | { type: 'already_retrieved' }
  | { type: 'expired' }
  | { type: 'not_found' }
  | { type: 'error'; message: string }

function getInitialParams(): { token: string | null; key: string | null } {
  const { token, key } = extractFromFragment()
  return { token: token || null, key: key || null }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

export default function ViewSecret() {
  useEffect(() => {
    document.title = 'View Secret | In The Event Of My Death'
  }, [])

  const [params] = useState(getInitialParams)
  const [state, setState] = useState<State>(() =>
    params.token ? { type: 'loading' } : { type: 'missing_params' },
  )
  const [countdown, setCountdown] = useState<string>('')

  const checkStatus = useCallback(async (decryptToken: string) => {
    try {
      const status = await getSecretStatus(decryptToken)

      if (!status.exists || status.status === 'not_found') {
        setState({ type: 'not_found' })
        return
      }

      if (status.status === 'retrieved') {
        setState({ type: 'already_retrieved' })
        return
      }

      if (status.status === 'expired') {
        setState({ type: 'expired' })
        return
      }

      if (status.status === 'pending' && status.unlock_at) {
        setState({
          type: 'pending',
          unlockAt: new Date(status.unlock_at),
          expiresAt: status.expires_at ? new Date(status.expires_at) : undefined,
        })
        return
      }

      if (status.status === 'available') {
        setState({ type: 'ready' })
      }
    } catch {
      setState({ type: 'error', message: 'Failed to check secret status' })
    }
  }, [])

  useEffect(() => {
    if (params.token) {
      checkStatus(params.token)
    }
  }, [params.token, checkStatus])

  useEffect(() => {
    if (state.type !== 'decrypted') return
    return () => {
      for (const attachment of state.attachments) {
        URL.revokeObjectURL(attachment.url)
      }
    }
  }, [state])

  // Countdown timer for pending secrets
  useEffect(() => {
    if (state.type !== 'pending') return

    const updateCountdown = () => {
      const now = new Date()
      const diff = state.unlockAt.getTime() - now.getTime()

      if (diff <= 0) {
        // Refresh status
        if (params.token) checkStatus(params.token)
        return
      }

      const days = Math.floor(diff / (1000 * 60 * 60 * 24))
      const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60))
      const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60))
      const seconds = Math.floor((diff % (1000 * 60)) / 1000)

      if (days > 0) {
        setCountdown(`${days}d ${hours}h ${minutes}m`)
      } else if (hours > 0) {
        setCountdown(`${hours}h ${minutes}m ${seconds}s`)
      } else {
        setCountdown(`${minutes}m ${seconds}s`)
      }
    }

    updateCountdown()
    const interval = setInterval(updateCountdown, 1000)
    return () => clearInterval(interval)
  }, [state, params.token, checkStatus])

  const handleRetrieve = async () => {
    if (!params.token) return

    setState({ type: 'retrieving' })

    try {
      const result = await retrieveSecret(params.token)

      if (result.status === 'pending') {
        if (result.unlock_at) {
          setState({ type: 'pending', unlockAt: new Date(result.unlock_at) })
        }
        return
      }

      if (result.status === 'retrieved') {
        setState({ type: 'already_retrieved' })
        return
      }

      if (result.status === 'available' && result.ciphertext && result.iv && result.auth_tag) {
        // Decrypt the message
        if (!params.key) {
          setState({
            type: 'error',
            message: 'Missing encryption key. The key should be in the URL fragment.',
          })
          return
        }

        const decryptedBytes = await decryptBytes(
          {
            ciphertext: result.ciphertext,
            iv: result.iv,
            authTag: result.auth_tag,
          },
          params.key,
        )

        const decoded = decodeSecretPayload(decryptedBytes)
        const attachments = decoded.attachments.map((a) => {
          const buffer = a.bytes.buffer.slice(
            a.bytes.byteOffset,
            a.bytes.byteOffset + a.bytes.byteLength,
          ) as ArrayBuffer
          const blob = new Blob([buffer], { type: a.type || 'application/octet-stream' })
          return {
            name: a.name,
            type: a.type || 'application/octet-stream',
            size: a.bytes.length,
            url: URL.createObjectURL(blob),
          }
        })

        setState({ type: 'decrypted', text: decoded.text, attachments })
      }
    } catch (err) {
      setState({
        type: 'error',
        message: err instanceof Error ? err.message : 'Failed to retrieve secret',
      })
    }
  }

  if (state.type === 'loading') {
    return (
      <div className="view-secret">
        <div className="loading">Loading...</div>
      </div>
    )
  }

  if (state.type === 'missing_params') {
    return (
      <div className="view-secret">
        <h1>Invalid Link</h1>
        <p>This link is missing the required token. Please check the URL and try again.</p>
      </div>
    )
  }

  if (state.type === 'not_found') {
    return (
      <div className="view-secret">
        <h1>Secret Not Found</h1>
        <p>
          This secret doesn't exist. It may have been deleted, already retrieved, or the link may be
          incorrect.
        </p>
      </div>
    )
  }

  if (state.type === 'already_retrieved') {
    return (
      <div className="view-secret">
        <h1>Already Retrieved</h1>
        <p>
          This secret has already been retrieved and is no longer available. Secrets can only be
          accessed once.
        </p>
      </div>
    )
  }

  if (state.type === 'expired') {
    return (
      <div className="view-secret">
        <h1>Secret Expired</h1>
        <p>
          This secret has expired and is no longer available. The secret was automatically deleted
          after its expiry date.
        </p>
      </div>
    )
  }

  if (state.type === 'pending') {
    return (
      <div className="view-secret">
        <h1>Secret Locked</h1>
        <p>This secret will be available in:</p>
        <div className="countdown">{countdown}</div>
        <p className="unlock-date">
          Unlocks on: {state.unlockAt.toLocaleDateString()} at {state.unlockAt.toLocaleTimeString()}
        </p>
        {state.expiresAt && (
          <p className="expiry-date">
            Expires on: {state.expiresAt.toLocaleDateString()} at{' '}
            {state.expiresAt.toLocaleTimeString()}
          </p>
        )}
      </div>
    )
  }

  if (state.type === 'ready') {
    return (
      <div className="view-secret">
        <h1>Secret Available</h1>
        <div className="warning">
          <strong>Warning:</strong> This secret can only be retrieved once. After you click the
          button below, it will be permanently deleted.
        </div>
        <button onClick={handleRetrieve} className="button primary">
          Retrieve Secret
        </button>
      </div>
    )
  }

  if (state.type === 'retrieving') {
    return (
      <div className="view-secret">
        <h1>Retrieving Secret</h1>
        <div className="loading">Decrypting...</div>
      </div>
    )
  }

  if (state.type === 'decrypted') {
    return (
      <div className="view-secret">
        <h1>Your Secret</h1>
        <div className="secret-content">
          {state.text && <pre>{state.text}</pre>}
          {state.attachments.length > 0 && (
            <div className="attachments">
              <h2>Attachments</h2>
              <ul>
                {state.attachments.map((a, index) => (
                  <li key={`${index}-${a.name}-${a.size}`}>
                    <a href={a.url} download={a.name}>
                      {a.name}
                    </a>{' '}
                    <span className="helper-text">
                      ({formatBytes(a.size)}
                      {a.type ? `, ${a.type}` : ''})
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <div className="info">
          This secret has been deleted from our servers. Save this message if you need to keep it.
        </div>
      </div>
    )
  }

  if (state.type === 'error') {
    return (
      <div className="view-secret">
        <h1>Error</h1>
        <div className="error-message">{state.message}</div>
      </div>
    )
  }

  return null
}
