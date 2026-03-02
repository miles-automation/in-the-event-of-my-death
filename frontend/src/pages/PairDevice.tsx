import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { unwrapVaultKeyWithPassword } from '../services/vault-crypto'
import { getVaultKeyIfExists, getEntries } from '../services/vault'
import { importAndSync } from '../services/vault-sync'
import type { VaultEntry } from '../types'

type State =
  | { type: 'input' }
  | { type: 'pairing' }
  | { type: 'merge_prompt'; vaultKey: string; existingEntryCount: number }
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

  const completePairing = async (vaultKeyBase64: string, entriesToMerge: VaultEntry[]) => {
    setState({ type: 'pairing' })
    try {
      const result = await importAndSync(vaultKeyBase64, entriesToMerge)
      if (result.status === 'error') {
        setState({ type: 'error', message: result.error || 'Sync failed after pairing' })
        return
      }
      setState({ type: 'success' })
      setTimeout(() => navigate('/my-secrets'), 1500)
    } catch {
      setState({ type: 'error', message: 'Failed to sync after pairing.' })
    }
  }

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

      // Check if this device has a different vault with entries
      const currentKey = await getVaultKeyIfExists()
      const entries = await getEntries()

      if (currentKey && currentKey !== vaultKeyBase64 && entries.length > 0) {
        setState({
          type: 'merge_prompt',
          vaultKey: vaultKeyBase64,
          existingEntryCount: entries.length,
        })
        return
      }

      // No conflict — import directly
      await completePairing(vaultKeyBase64, [])
    } catch {
      setState({
        type: 'error',
        message: 'Incorrect password or invalid pairing link.',
      })
    }
  }

  const handleMergeChoice = async (mode: 'merge' | 'switch') => {
    if (state.type !== 'merge_prompt') return
    const entriesToMerge = mode === 'merge' ? await getEntries() : []
    await completePairing(state.vaultKey, entriesToMerge)
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

  if (state.type === 'merge_prompt') {
    return (
      <div className="pair-device">
        <h1>Pair Device</h1>
        <div className="modal-overlay">
          <div className="modal">
            <h2>Different Vault Detected</h2>
            <p className="helper-text">
              This device has {state.existingEntryCount} existing{' '}
              {state.existingEntryCount === 1 ? 'secret' : 'secrets'} in a different vault. How
              would you like to proceed?
            </p>
            <div className="merge-options">
              <button onClick={() => handleMergeChoice('merge')} className="button primary">
                Merge
              </button>
              <p className="helper-text">
                Combine your {state.existingEntryCount} existing{' '}
                {state.existingEntryCount === 1 ? 'secret' : 'secrets'} into the paired vault.
              </p>
              <button onClick={() => handleMergeChoice('switch')} className="button secondary">
                Switch
              </button>
              <p className="helper-text warning">
                Switch to the paired vault without merging. Your existing secrets will only be
                recoverable if you have a recovery kit for your current vault.
              </p>
            </div>
            <button
              onClick={() => setState({ type: 'input' })}
              className="button text small"
              style={{ marginTop: '0.5rem' }}
            >
              Cancel
            </button>
          </div>
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
