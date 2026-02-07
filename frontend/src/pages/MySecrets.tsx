import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { getEntries, updateEntry, deleteEntry } from '../services/vault'
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
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [editingLabel, setEditingLabel] = useState<string | null>(null)
  const [labelDraft, setLabelDraft] = useState('')

  useEffect(() => {
    document.title = 'My Secrets | In The Event Of My Death'
  }, [])

  const loadEntries = useCallback(async () => {
    try {
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
        </div>
      </div>
    )
  }

  return (
    <div className="my-secrets">
      <h1>My Secrets</h1>

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
