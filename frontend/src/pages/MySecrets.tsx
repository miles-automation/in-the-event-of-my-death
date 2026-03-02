import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { getEntries, updateEntry, deleteEntry, initVault, importVaultKey } from '../services/vault'
import { syncVault } from '../services/vault-sync'
import { wrapVaultKeyWithPassword } from '../services/vault-crypto'
import { getEditSecretStatus } from '../services/api'
import { formatDateForDisplay } from '../utils/dates'
import type { VaultEntry, VaultEntryStatus } from '../types'

type State =
  | { type: 'loading' }
  | { type: 'loaded'; entries: VaultEntry[] }
  | { type: 'empty' }
  | { type: 'error'; message: string }

function statusLabel(status?: VaultEntryStatus): string {
  switch (status) {
    case 'pending':
      return 'Pending'
    case 'unlocked':
      return 'Unlocked'
    case 'retrieved':
      return 'Retrieved'
    case 'expired':
      return 'Expired'
    default:
      return 'Unknown'
  }
}

function statusClass(status?: VaultEntryStatus): string {
  switch (status) {
    case 'pending':
      return 'status-badge pending'
    case 'unlocked':
      return 'status-badge unlocked'
    case 'retrieved':
      return 'status-badge retrieved'
    case 'expired':
      return 'status-badge expired'
    default:
      return 'status-badge'
  }
}

function mapApiStatus(apiStatus: string): VaultEntryStatus {
  switch (apiStatus) {
    case 'pending':
      return 'pending'
    case 'available':
      return 'unlocked'
    case 'retrieved':
      return 'retrieved'
    case 'expired':
      return 'expired'
    case 'not_found':
      return 'expired'
    default:
      return 'pending'
  }
}

export default function MySecrets() {
  const [state, setState] = useState<State>({ type: 'loading' })
  const [refreshing, setRefreshing] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [editingLabel, setEditingLabel] = useState<string | null>(null)
  const [labelDraft, setLabelDraft] = useState('')
  const [showPairModal, setShowPairModal] = useState(false)
  const [pairPassword, setPairPassword] = useState('')
  const [pairLink, setPairLink] = useState('')
  const [pairCopied, setPairCopied] = useState(false)
  const [recoveryImporting, setRecoveryImporting] = useState(false)
  const [showExportModal, setShowExportModal] = useState(false)
  const [exportKitJson, setExportKitJson] = useState('')
  const [exportCopied, setExportCopied] = useState(false)

  useEffect(() => {
    document.title = 'My Secrets | In The Event Of My Death'
  }, [])

  const loadEntries = useCallback(async () => {
    try {
      // Sync with server first (merges remote entries into local)
      setSyncing(true)
      try {
        const { vaultKey } = await initVault()
        const result = await syncVault(vaultKey)
        if (result.status !== 'error') {
          setSyncing(false)
          const entries = result.entriesAfterSync
          if (entries.length === 0) {
            setState({ type: 'empty' })
          } else {
            const sorted = [...entries].sort(
              (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
            )
            setState({ type: 'loaded', entries: sorted })
          }
          return
        }
      } catch {
        // Sync failed — fall back to local entries
      }
      setSyncing(false)

      const entries = await getEntries()
      if (entries.length === 0) {
        setState({ type: 'empty' })
      } else {
        // Sort by creation date, newest first
        const sorted = [...entries].sort(
          (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
        )
        setState({ type: 'loaded', entries: sorted })
      }
    } catch (err) {
      setState({
        type: 'error',
        message: err instanceof Error ? err.message : 'Failed to load vault',
      })
    }
  }, [])

  const refreshStatuses = useCallback(async () => {
    if (state.type !== 'loaded') return

    setRefreshing(true)
    const now = new Date().toISOString()

    const updated = await Promise.all(
      state.entries.map(async (entry) => {
        try {
          const resp = await getEditSecretStatus(entry.editToken)
          const newStatus: VaultEntryStatus = resp.exists ? mapApiStatus(resp.status) : 'expired'

          if (newStatus !== entry.status) {
            await updateEntry(entry.secretId, { status: newStatus, lastCheckedAt: now })
          } else {
            await updateEntry(entry.secretId, { lastCheckedAt: now })
          }

          return {
            ...entry,
            status: newStatus,
            lastCheckedAt: now,
            // Update timestamps from server if available
            ...(resp.unlock_at ? { unlockAt: resp.unlock_at } : {}),
            ...(resp.expires_at ? { expiresAt: resp.expires_at } : {}),
          }
        } catch {
          // API error (404, 410, etc.) — mark as expired or retrieved
          const newStatus: VaultEntryStatus = 'expired'
          try {
            await updateEntry(entry.secretId, { status: newStatus, lastCheckedAt: now })
          } catch {
            // IndexedDB write failed — ignore
          }
          return { ...entry, status: newStatus, lastCheckedAt: now }
        }
      }),
    )

    setState({ type: 'loaded', entries: updated })
    setRefreshing(false)
  }, [state])

  useEffect(() => {
    loadEntries()
  }, [loadEntries])

  // Refresh statuses after entries are loaded
  useEffect(() => {
    if (state.type === 'loaded') {
      refreshStatuses()
    }
    // Only run when we first load entries, not on every state change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.type === 'loaded' ? 'loaded' : 'not'])

  const handleDelete = async (secretId: string) => {
    try {
      await deleteEntry(secretId)
      setConfirmDelete(null)
      await loadEntries()
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to delete entry'
      setState({ type: 'error', message })
    }
  }

  const startEditingLabel = (entry: VaultEntry) => {
    setEditingLabel(entry.secretId)
    setLabelDraft(entry.label || '')
  }

  const saveLabel = async (secretId: string) => {
    const trimmed = labelDraft.trim()
    try {
      await updateEntry(secretId, { label: trimmed || undefined })
      if (state.type === 'loaded') {
        setState({
          type: 'loaded',
          entries: state.entries.map((e) =>
            e.secretId === secretId ? { ...e, label: trimmed || undefined } : e,
          ),
        })
      }
    } catch {
      // IndexedDB write failed — ignore
    }
    setEditingLabel(null)
  }

  const generatePairLink = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!pairPassword) return

    try {
      const { vaultKey } = await initVault()
      const { encrypted, salt } = await wrapVaultKeyWithPassword(vaultKey, pairPassword)
      const link = `${window.location.origin}/pair#encrypted=${encodeURIComponent(encrypted)}&salt=${encodeURIComponent(salt)}`
      setPairLink(link)
    } catch {
      // Crypto failure — unlikely but handle gracefully
      setPairLink('')
    }
  }

  const copyPairLink = async () => {
    await navigator.clipboard.writeText(pairLink)
    setPairCopied(true)
    setTimeout(() => setPairCopied(false), 2000)
  }

  const closePairModal = () => {
    setShowPairModal(false)
    setPairPassword('')
    setPairLink('')
    setPairCopied(false)
  }

  const openExportModal = async () => {
    try {
      const { vaultKey } = await initVault()
      const kit = {
        version: 1,
        vaultKey,
        exportedAt: new Date().toISOString(),
        warning:
          'This file contains your vault key. Anyone with this file can access your vault. Store it securely.',
      }
      setExportKitJson(JSON.stringify(kit, null, 2))
      setShowExportModal(true)
    } catch {
      // Vault key unavailable
    }
  }

  const downloadRecoveryKit = () => {
    const blob = new Blob([exportKitJson], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'ieomd-recovery-kit.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  const copyRecoveryKit = async () => {
    await navigator.clipboard.writeText(exportKitJson)
    setExportCopied(true)
    setTimeout(() => setExportCopied(false), 2000)
  }

  const closeExportModal = () => {
    setShowExportModal(false)
    setExportKitJson('')
    setExportCopied(false)
  }

  const importRecoveryKit = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setRecoveryImporting(true)
    try {
      const text = await file.text()
      const kit = JSON.parse(text)
      if (!kit.vaultKey || kit.version !== 1) {
        throw new Error('Invalid recovery kit format')
      }
      await importVaultKey(kit.vaultKey)
      await syncVault(kit.vaultKey)
      await loadEntries()
    } catch (err) {
      setState({
        type: 'error',
        message: err instanceof Error ? err.message : 'Failed to import recovery kit',
      })
    }
    setRecoveryImporting(false)
    // Reset file input
    e.target.value = ''
  }

  if (state.type === 'loading') {
    return (
      <div className="my-secrets">
        <h1>My Secrets</h1>
        <div className="loading">
          <div className="spinner"></div>
          <p>Loading vault...</p>
        </div>
      </div>
    )
  }

  if (state.type === 'error') {
    return (
      <div className="my-secrets">
        <h1>My Secrets</h1>
        <div className="error-message">
          <p>{state.message}</p>
        </div>
        <button onClick={loadEntries} className="button secondary">
          Try Again
        </button>
      </div>
    )
  }

  if (state.type === 'empty') {
    return (
      <div className="my-secrets">
        <h1>My Secrets</h1>
        <div className="empty-state">
          <p>No secrets tracked yet.</p>
          <p className="helper-text">
            Secrets you create will automatically appear here for tracking.
          </p>
          <Link to="/" className="button primary">
            Create Your First Secret
          </Link>
          <div style={{ marginTop: '1.5rem' }}>
            <p className="helper-text">Have a recovery kit or pairing link?</p>
            <label className="button secondary small" style={{ cursor: 'pointer' }}>
              {recoveryImporting ? 'Importing...' : 'Import Recovery Kit'}
              <input
                type="file"
                accept=".json"
                onChange={importRecoveryKit}
                style={{ display: 'none' }}
                disabled={recoveryImporting}
              />
            </label>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="my-secrets">
      <h1>My Secrets</h1>

      <div className="vault-actions">
        <button onClick={() => setShowPairModal(true)} className="button secondary small">
          Pair Device
        </button>
        <button onClick={openExportModal} className="button secondary small">
          Export Recovery Kit
        </button>
      </div>

      {showPairModal && (
        <div className="modal-overlay" onClick={closePairModal}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Pair Another Device</h2>
            {!pairLink ? (
              <form onSubmit={generatePairLink}>
                <p className="helper-text">
                  Set a password to protect the pairing link. Share the link and password
                  separately.
                </p>
                <div className="form-group">
                  <label htmlFor="pair-pw">Password</label>
                  <input
                    id="pair-pw"
                    type="password"
                    value={pairPassword}
                    onChange={(e) => setPairPassword(e.target.value)}
                    placeholder="Choose a password"
                    autoFocus
                    required
                    minLength={4}
                  />
                </div>
                <button type="submit" className="button primary" disabled={!pairPassword}>
                  Generate Link
                </button>
              </form>
            ) : (
              <div>
                <p className="helper-text">
                  Copy this link and open it on your other device. You will need the password to
                  complete pairing.
                </p>
                <div className="pair-link-box">
                  <code className="pair-link-text">{pairLink.slice(0, 60)}...</code>
                  <button onClick={copyPairLink} className="button secondary small">
                    {pairCopied ? 'Copied!' : 'Copy'}
                  </button>
                </div>
                <p className="helper-text warning">
                  This link contains your encrypted vault key. Only share it with yourself.
                </p>
              </div>
            )}
            <button
              onClick={closePairModal}
              className="button text small"
              style={{ marginTop: '0.5rem' }}
            >
              Close
            </button>
          </div>
        </div>
      )}

      {showExportModal && (
        <div className="modal-overlay" onClick={closeExportModal}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Recovery Kit</h2>
            <div className="warning">
              <p style={{ margin: 0 }}>
                <strong>Treat this like a password.</strong> Anyone with this file can access your
                vault. Store it somewhere safe and offline.
              </p>
            </div>
            <div className="export-kit-actions">
              <button onClick={downloadRecoveryKit} className="button primary small">
                Download
              </button>
              <button onClick={copyRecoveryKit} className="button secondary small">
                {exportCopied ? 'Copied!' : 'Copy to Clipboard'}
              </button>
            </div>
            <button
              onClick={closeExportModal}
              className="button text small"
              style={{ marginTop: '0.5rem' }}
            >
              Close
            </button>
          </div>
        </div>
      )}

      {syncing && <p className="refresh-indicator">Syncing vault...</p>}
      {refreshing && <p className="refresh-indicator">Refreshing statuses...</p>}

      <div className="secrets-list">
        {state.entries.map((entry) => {
          const unlock = formatDateForDisplay(new Date(entry.unlockAt))
          const expiry = formatDateForDisplay(new Date(entry.expiresAt))

          return (
            <div key={entry.secretId} className="secret-card">
              <div className="secret-card-header">
                {editingLabel === entry.secretId ? (
                  <input
                    className="secret-label-input"
                    type="text"
                    value={labelDraft}
                    onChange={(e) => setLabelDraft(e.target.value)}
                    onBlur={() => saveLabel(entry.secretId)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') saveLabel(entry.secretId)
                      if (e.key === 'Escape') setEditingLabel(null)
                    }}
                    placeholder="Add a label..."
                    autoFocus
                    maxLength={100}
                  />
                ) : (
                  <span
                    className={`secret-label ${!entry.label ? 'secret-label-placeholder' : ''}`}
                    onClick={() => startEditingLabel(entry)}
                    title="Click to add a label"
                  >
                    {entry.label || 'Add a label...'}
                  </span>
                )}
                <span className={statusClass(entry.status)}>{statusLabel(entry.status)}</span>
              </div>

              {entry.recipientHint && (
                <p className="secret-recipient">For: {entry.recipientHint}</p>
              )}

              <div className="secret-dates">
                {unlock && (
                  <p className="secret-date">
                    <span className="date-label">Unlocks:</span> {unlock.date} at {unlock.time}
                  </p>
                )}
                {expiry && (
                  <p className="secret-date">
                    <span className="date-label">Expires:</span> {expiry.date} at {expiry.time}
                  </p>
                )}
              </div>

              <div className="secret-card-actions">
                {entry.status !== 'retrieved' && entry.status !== 'expired' && (
                  <Link to={`/edit#token=${entry.editToken}`} className="button secondary small">
                    Edit
                  </Link>
                )}
                {confirmDelete === entry.secretId ? (
                  <span className="confirm-delete">
                    <span className="helper-text">Remove from vault?</span>
                    <button
                      onClick={() => handleDelete(entry.secretId)}
                      className="button danger small"
                    >
                      Yes
                    </button>
                    <button
                      onClick={() => setConfirmDelete(null)}
                      className="button secondary small"
                    >
                      No
                    </button>
                  </span>
                ) : (
                  <button
                    onClick={() => setConfirmDelete(entry.secretId)}
                    className="button text small"
                  >
                    Remove
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
