import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { unwrapVaultKeyWithPassword } from '../services/vault-crypto'
import { importVaultKey } from '../services/vault'
import { syncVault } from '../services/vault-sync'

type State =
  | { type: 'input' }
  | { type: 'pairing' }
  | { type: 'success' }
  | { type: 'error'; message: string }

function parseFragment(): { encrypted?: string; salt?: string } {
  const hash = window.location.hash.slice(1)
  const params = new URLSearchParams(hash)
  return {
    encrypted: params.get('encrypted') ?? undefined,
    salt: params.get('salt') ?? undefined,
  }
}

export default function PairDevice() {
  const navigate = useNavigate()
  const [state, setState] = useState<State>({ type: 'input' })
  const [password, setPassword] = useState('')
  const [fragment] = useState(parseFragment)

  useEffect(() => {
    document.title = 'Pair Device | In The Event Of My Death'
  }, [])

  const hasValidFragment = fragment.encrypted && fragment.salt

  const handlePair = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!fragment.encrypted || !fragment.salt || !password) return

    setState({ type: 'pairing' })

    try {
      // Decrypt the vaultKey using the password
      const vaultKeyBase64 = await unwrapVaultKeyWithPassword(
        fragment.encrypted,
        fragment.salt,
        password,
      )

      // Import into local vault
      await importVaultKey(vaultKeyBase64)

      // Sync from server to pull all entries
      const result = await syncVault(vaultKeyBase64)

      if (result.status === 'error') {
        setState({ type: 'error', message: result.error || 'Sync failed after pairing' })
        return
      }

      setState({ type: 'success' })
      setTimeout(() => navigate('/my-secrets'), 1500)
    } catch {
      setState({
        type: 'error',
        message: 'Incorrect password or invalid pairing link.',
      })
    }
  }

  if (!hasValidFragment) {
    return (
      <div className="pair-device">
        <h1>Pair Device</h1>
        <div className="error-message">
          <p>Invalid or missing pairing link.</p>
          <p className="helper-text">
            To pair this device, open the pairing link generated from your other device.
          </p>
        </div>
        <Link to="/my-secrets" className="button secondary">
          Go to My Secrets
        </Link>
      </div>
    )
  }

  if (state.type === 'success') {
    return (
      <div className="pair-device">
        <h1>Pair Device</h1>
        <div className="success-message">
          <p>Device paired successfully! Redirecting to your vault...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="pair-device">
      <h1>Pair Device</h1>
      <p className="helper-text">
        Enter the password that was set when this pairing link was created.
      </p>

      <form onSubmit={handlePair}>
        <div className="form-group">
          <label htmlFor="pair-password">Password</label>
          <input
            id="pair-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Enter pairing password"
            disabled={state.type === 'pairing'}
            autoFocus
            required
          />
        </div>

        {state.type === 'error' && (
          <div className="error-message">
            <p>{state.message}</p>
          </div>
        )}

        <button
          type="submit"
          className="button primary"
          disabled={state.type === 'pairing' || !password}
        >
          {state.type === 'pairing' ? 'Pairing...' : 'Pair This Device'}
        </button>
      </form>

      <p className="helper-text" style={{ marginTop: '1rem' }}>
        Your vault key is encrypted in the link. The password never leaves this device.
      </p>
    </div>
  )
}
