import { useState, useEffect, useRef } from 'react'
import { generateSecretFromBytes, base64ToBytes } from '../services/crypto'
import { requestChallenge, createSecret } from '../services/api'
import { solveChallenge } from '../services/pow'
import { encodeSecretPayloadV1 } from '../services/secretPayload'
import { generateShareableLinks } from '../utils/urlFragments'
import {
  applyDateOffset,
  validateExpiryDate,
  type UnlockPreset,
  type ExpiryPreset,
} from '../utils/dates'
import type { ShareableLinks } from '../types'

type Step = 'input' | 'processing' | 'done'

const MAX_POW_CIPHERTEXT_BYTES = 1_000_000

// File attachment limits
const MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024 // 50MB per file
const MAX_TOTAL_SIZE_BYTES = 100 * 1024 * 1024 // 100MB total
const MAX_FILES = 10

export default function Home() {
  const [step, setStep] = useState<Step>('input')
  const [message, setMessage] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [capabilityToken, setCapabilityToken] = useState('')
  const [showCapabilityToken, setShowCapabilityToken] = useState(false)
  const [unlockPreset, setUnlockPreset] = useState<UnlockPreset>('now')
  const [customUnlockDate, setCustomUnlockDate] = useState('')
  const [customUnlockTime, setCustomUnlockTime] = useState('00:00')
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState<string>('')
  const [links, setLinks] = useState<ShareableLinks | null>(null)
  const [copied, setCopied] = useState<'edit' | 'view' | null>(null)
  const canShare = typeof navigator !== 'undefined' && !!navigator.share

  // Expiry date state
  const [expiryPreset, setExpiryPreset] = useState<ExpiryPreset>('1h')
  const [customExpiryDate, setCustomExpiryDate] = useState('')
  const [customExpiryTime, setCustomExpiryTime] = useState('00:00')
  const [createdUnlockAt, setCreatedUnlockAt] = useState<Date | null>(null)
  const [createdExpiresAt, setCreatedExpiresAt] = useState<Date | null>(null)

  // Dropdown open state
  const [unlockOpen, setUnlockOpen] = useState(false)
  const [expiryOpen, setExpiryOpen] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const unlockRef = useRef<HTMLDivElement>(null)
  const expiryRef = useRef<HTMLDivElement>(null)
  const attachmentInputRef = useRef<HTMLInputElement>(null)

  // Tick state to trigger re-renders for live time updates
  const [, setTick] = useState(0)

  useEffect(() => {
    document.title = 'In The Event Of My Death'
  }, [])

  useEffect(() => {
    // Only tick when on input step and using non-custom presets (they depend on current time)
    if (step === 'input' && (unlockPreset !== 'custom' || expiryPreset !== 'custom')) {
      const interval = setInterval(() => setTick((t) => t + 1), 1000)
      return () => clearInterval(interval)
    }
  }, [step, unlockPreset, expiryPreset])

  // Close dropdowns when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (unlockRef.current && !unlockRef.current.contains(e.target as Node)) {
        setUnlockOpen(false)
      }
      if (expiryRef.current && !expiryRef.current.contains(e.target as Node)) {
        setExpiryOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Calculate unlock date from preset
  const getUnlockDate = (): Date | null => {
    return applyDateOffset(new Date(), unlockPreset, {
      date: customUnlockDate,
      time: customUnlockTime,
    })
  }

  // Calculate expiry date from preset (relative to unlock date)
  const getExpiryDate = (unlockDate: Date): Date | null => {
    return applyDateOffset(unlockDate, expiryPreset, {
      date: customExpiryDate,
      time: customExpiryTime,
    })
  }

  // Check if form is valid
  const hasContent = message.trim().length > 0 || files.length > 0
  const isValid =
    hasContent &&
    (unlockPreset !== 'custom' || (customUnlockDate && customUnlockTime)) &&
    (expiryPreset !== 'custom' || (customExpiryDate && customExpiryTime))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (!hasContent) {
      setError('Please enter a message or attach a file')
      return
    }

    const unlockAt = getUnlockDate()
    if (!unlockAt) {
      setError('Please select an unlock date')
      return
    }

    // Only validate future date for custom presets
    if (unlockPreset === 'custom' && unlockAt <= new Date()) {
      setError('Unlock date must be in the future')
      return
    }

    // Calculate expiry date based on selected preset
    const expiresAt = getExpiryDate(unlockAt)
    if (!expiresAt) {
      setError('Please select an expiry date')
      return
    }

    // Validate expiry constraints
    const expiryError = validateExpiryDate(unlockAt, expiresAt)
    if (expiryError) {
      setError(expiryError)
      return
    }

    setStep('processing')

    try {
      // Step 1: Read attachments and build payload
      setProgress(files.length > 0 ? 'Preparing attachments...' : 'Preparing your secret...')
      const attachments = await Promise.all(
        files.map(async (file) => {
          try {
            return {
              name: file.name,
              type: file.type || 'application/octet-stream',
              bytes: new Uint8Array(await file.arrayBuffer()),
            }
          } catch (err) {
            const reason = err instanceof Error ? err.message : 'unknown error'
            throw new Error(`Failed to read file "${file.name}": ${reason}`)
          }
        }),
      )

      const payloadBytes = encodeSecretPayloadV1({
        text: message,
        attachments,
      })

      // Step 2: Generate cryptographic materials
      setProgress('Encrypting your secret...')
      const secret = await generateSecretFromBytes(payloadBytes)

      const ciphertextSize = base64ToBytes(secret.encrypted.ciphertext).length

      const trimmedCapabilityToken = capabilityToken.trim() || null

      // Step 3: Create secret on server (PoW or capability token)
      setProgress('Storing encrypted secret...')
      const createRequest: Parameters<typeof createSecret>[0] = {
        ciphertext: secret.encrypted.ciphertext,
        iv: secret.encrypted.iv,
        auth_tag: secret.encrypted.authTag,
        edit_token: secret.editToken,
        decrypt_token: secret.decryptToken,
      }

      // Send presets for server-calculated times (avoids clock skew), or absolute times for custom
      if (unlockPreset !== 'custom') {
        createRequest.unlock_preset = unlockPreset
      } else {
        createRequest.unlock_at = unlockAt.toISOString()
      }

      if (expiryPreset !== 'custom') {
        createRequest.expiry_preset = expiryPreset
      } else {
        createRequest.expires_at = expiresAt.toISOString()
      }

      const response = trimmedCapabilityToken
        ? await createSecret(createRequest, { capabilityToken: trimmedCapabilityToken })
        : await (async () => {
            if (ciphertextSize > MAX_POW_CIPHERTEXT_BYTES) {
              throw new Error(
                'This secret is too large for proof-of-work. Add a capability token to upload larger files.',
              )
            }

            // Request PoW challenge
            setProgress('Requesting proof-of-work challenge...')
            const challenge = await requestChallenge(secret.payloadHash, ciphertextSize)

            // Solve PoW
            setProgress(`Solving proof-of-work (difficulty: ${challenge.difficulty})...`)
            const powProof = await solveChallenge(challenge, secret.payloadHash, (iterations) => {
              setProgress(
                `Solving proof-of-work... (${(iterations / 1000).toFixed(0)}k iterations)`,
              )
            })

            createRequest.pow_proof = powProof
            setProgress('Storing encrypted secret...')
            return createSecret(createRequest)
          })()

      // Step 4: Generate shareable links
      const shareableLinks = generateShareableLinks(
        secret.editToken,
        secret.decryptToken,
        secret.encryptionKey,
      )

      setLinks(shareableLinks)
      // Use server-provided times (accurate, no clock skew)
      setCreatedUnlockAt(new Date(response.unlock_at))
      setCreatedExpiresAt(new Date(response.expires_at))
      setStep('done')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An unexpected error occurred')
      setStep('input')
    }
  }

  const copyToClipboard = async (text: string, type: 'edit' | 'view') => {
    await navigator.clipboard.writeText(text)
    setCopied(type)
    setTimeout(() => setCopied(null), 2000)
  }

  const shareLink = async (url: string) => {
    if (!navigator.share) return
    try {
      await navigator.share({
        title: 'Someone shared a secret with you',
        url,
      })
    } catch {
      // User cancelled or share failed - silently ignore
      // AbortError is expected when user dismisses share sheet
    }
  }

  const resetForm = () => {
    setStep('input')
    setMessage('')
    setFiles([])
    if (attachmentInputRef.current) {
      attachmentInputRef.current.value = ''
    }
    setCapabilityToken('')
    setShowCapabilityToken(false)
    setUnlockPreset('now')
    setCustomUnlockDate('')
    setCustomUnlockTime('00:00')
    setExpiryPreset('1h')
    setCustomExpiryDate('')
    setCustomExpiryTime('00:00')
    setCreatedUnlockAt(null)
    setCreatedExpiresAt(null)
    setLinks(null)
    setError(null)
  }

  const openAttachmentPicker = () => {
    attachmentInputRef.current?.click()
  }

  const addFiles = (incoming: File[]) => {
    if (incoming.length === 0) return
    setError(null)

    // Validate individual file sizes
    const oversizedFile = incoming.find((f) => f.size > MAX_FILE_SIZE_BYTES)
    if (oversizedFile) {
      setError(`File "${oversizedFile.name}" exceeds maximum size of 50MB`)
      return
    }

    // Compute merged list (deduplicated) to validate before updating state
    const merged = [...files]
    for (const file of incoming) {
      const key = `${file.name}:${file.size}:${file.lastModified}`
      const already = merged.some((f) => `${f.name}:${f.size}:${f.lastModified}` === key)
      if (!already) merged.push(file)
    }

    // Validate total count
    if (merged.length > MAX_FILES) {
      setError(`Maximum ${MAX_FILES} files allowed`)
      return
    }

    // Validate total size
    const totalSize = merged.reduce((sum, f) => sum + f.size, 0)
    if (totalSize > MAX_TOTAL_SIZE_BYTES) {
      setError(`Total file size exceeds maximum of 100MB`)
      return
    }

    setFiles(merged)
  }

  const removeFileAt = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index))
  }

  // Format bytes as human-readable size
  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
  }

  // Get file type icon based on MIME type
  const getFileIcon = (mimeType: string): string => {
    if (mimeType.startsWith('image/')) return '🖼️'
    if (mimeType.startsWith('audio/')) return '🎵'
    if (mimeType.startsWith('video/')) return '🎬'
    if (mimeType === 'application/pdf') return '📄'
    if (mimeType.startsWith('text/')) return '📝'
    if (
      [
        'application/zip',
        'application/x-rar-compressed',
        'application/gzip',
        'application/x-tar',
      ].includes(mimeType)
    )
      return '📦'
    return '📎'
  }

  if (step === 'processing') {
    return (
      <div className="home">
        <div className="hero-form">
          <h1>Creating Your Secret</h1>
          <div className="processing">
            <div className="spinner"></div>
            <p>{progress}</p>
          </div>
        </div>
      </div>
    )
  }

  if (step === 'done' && links) {
    return (
      <div className="home">
        <div className="hero-form success-state">
          <h1>Secret Created!</h1>

          <div className="success-message">
            <p>
              Your secret has been encrypted and stored. Save these links carefully - you won't see
              them again!
            </p>
          </div>

          {createdUnlockAt && createdExpiresAt && (
            <div className="dates-info">
              <p>
                <strong>Unlocks:</strong>{' '}
                {createdUnlockAt.toLocaleDateString(undefined, {
                  weekday: 'short',
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric',
                })}{' '}
                at{' '}
                {createdUnlockAt.toLocaleTimeString(undefined, {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </p>
              <p>
                <strong>Expires:</strong>{' '}
                {createdExpiresAt.toLocaleDateString(undefined, {
                  weekday: 'short',
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric',
                })}{' '}
                at{' '}
                {createdExpiresAt.toLocaleTimeString(undefined, {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </p>
            </div>
          )}

          <div className="links-section">
            <div className="link-box primary">
              <h3>Share Link</h3>
              <p className="link-description">Send this to who should receive your secret.</p>
              <div className="link-container">
                <input type="text" value={links.viewLink} readOnly />
                <button
                  onClick={() => copyToClipboard(links.viewLink, 'view')}
                  className="copy-button"
                >
                  {copied === 'view' ? 'Copied!' : 'Copy'}
                </button>
                {canShare && (
                  <button
                    onClick={() => shareLink(links.viewLink)}
                    className="share-button"
                    aria-label="Share secret link"
                  >
                    Share
                  </button>
                )}
              </div>
            </div>

            <div className="link-box secondary">
              <h3>Edit Link (keep private)</h3>
              <p className="link-description">Use this to extend the unlock date. Do not share.</p>
              <div className="link-container">
                <input type="text" value={links.editLink} readOnly />
                <button
                  onClick={() => copyToClipboard(links.editLink, 'edit')}
                  className="copy-button"
                >
                  {copied === 'edit' ? 'Copied!' : 'Copy'}
                </button>
              </div>
            </div>
          </div>

          <div className="warning">
            <strong>Important:</strong> The encryption key is in the URL fragment. If you lose these
            links, your secret cannot be recovered.
          </div>

          <button onClick={resetForm} className="button secondary">
            Create Another Secret
          </button>
        </div>
      </div>
    )
  }

  const unlockDate = getUnlockDate()

  return (
    <div className="home">
      <div className="hero-form">
        <p className="hero-title">In The Event Of My Death</p>
        <form onSubmit={handleSubmit} className="inline-form">
          <div
            className={`message-input-container${dragActive ? ' drag-active' : ''}`}
            onDragOver={(e) => {
              e.preventDefault()
              setDragActive(true)
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragActive(false)
              addFiles(Array.from(e.dataTransfer.files))
            }}
          >
            <textarea
              id="message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Enter your secret message..."
              rows={4}
              autoFocus
              aria-required={files.length === 0}
            />
            <input
              ref={attachmentInputRef}
              id="attachments"
              type="file"
              multiple
              className="attach-file-input"
              onChange={(e) => addFiles(e.target.files ? Array.from(e.target.files) : [])}
            />
            <button
              type="button"
              className="attach-button-overlay"
              onClick={openAttachmentPicker}
              aria-label="Attach files"
              title="Attach files"
            >
              📎
            </button>

            {files.length > 0 && (
              <div className="attachment-chips" role="list" aria-label="Attachments">
                {files.map((file, index) => (
                  <div
                    key={`${index}-${file.name}-${file.size}-${file.lastModified}`}
                    className="attachment-chip"
                    role="listitem"
                  >
                    <span className="attachment-chip-icon" aria-hidden="true">
                      {getFileIcon(file.type)}
                    </span>
                    <span className="attachment-chip-name" title={file.name}>
                      {file.name}
                    </span>
                    <button
                      type="button"
                      className="attachment-chip-remove"
                      onClick={() => removeFileAt(index)}
                      aria-label={`Remove ${file.name}`}
                      title="Remove"
                    >
                      ×
                    </button>
                  </div>
                ))}
                <span className="attachment-summary">
                  {files.length} {files.length === 1 ? 'file' : 'files'} (
                  {formatBytes(files.reduce((sum, f) => sum + f.size, 0))})
                </span>
              </div>
            )}
          </div>

          <div className="message-input-container">
            <button
              type="button"
              className="linkish-button"
              onClick={() => setShowCapabilityToken((s) => !s)}
            >
              {showCapabilityToken ? 'Hide capability token' : 'Have a capability token?'}
            </button>
            {showCapabilityToken && (
              <input
                id="capabilityToken"
                type="password"
                autoComplete="off"
                placeholder="Capability token (optional, for large files)"
                value={capabilityToken}
                onChange={(e) => setCapabilityToken(e.target.value)}
              />
            )}
          </div>

          <button
            type="submit"
            className="button primary full-width send-button"
            disabled={!isValid}
          >
            Send
          </button>

          <div className="date-toolbar">
            <div className="date-toolbar-item" ref={unlockRef}>
              <span className="date-toolbar-label">Unlocks</span>
              <button
                type="button"
                className="date-toolbar-select"
                onClick={() => {
                  setUnlockOpen(!unlockOpen)
                  setExpiryOpen(false)
                }}
              >
                {unlockPreset === 'now'
                  ? 'Now'
                  : unlockPreset === '15m'
                    ? '15 min'
                    : unlockPreset === '1h'
                      ? '1 hour'
                      : unlockPreset === '24h'
                        ? '24 hours'
                        : unlockPreset === '1w'
                          ? '1 week'
                          : 'Custom'}
                <span className="dropdown-arrow">▾</span>
              </button>
              {unlockOpen && (
                <div className="date-toolbar-dropdown">
                  <button
                    type="button"
                    className={unlockPreset === 'now' ? 'active' : ''}
                    onClick={() => {
                      setUnlockPreset('now')
                      setUnlockOpen(false)
                    }}
                  >
                    Now
                  </button>
                  <button
                    type="button"
                    className={unlockPreset === '15m' ? 'active' : ''}
                    onClick={() => {
                      setUnlockPreset('15m')
                      setUnlockOpen(false)
                    }}
                  >
                    15 min
                  </button>
                  <button
                    type="button"
                    className={unlockPreset === '1h' ? 'active' : ''}
                    onClick={() => {
                      setUnlockPreset('1h')
                      setUnlockOpen(false)
                    }}
                  >
                    1 hour
                  </button>
                  <button
                    type="button"
                    className={unlockPreset === '24h' ? 'active' : ''}
                    onClick={() => {
                      setUnlockPreset('24h')
                      setUnlockOpen(false)
                    }}
                  >
                    24 hours
                  </button>
                  <button
                    type="button"
                    className={unlockPreset === '1w' ? 'active' : ''}
                    onClick={() => {
                      setUnlockPreset('1w')
                      setUnlockOpen(false)
                    }}
                  >
                    1 week
                  </button>
                  <button
                    type="button"
                    className={unlockPreset === 'custom' ? 'active' : ''}
                    onClick={() => {
                      setUnlockPreset('custom')
                    }}
                  >
                    Custom
                  </button>
                  {unlockPreset === 'custom' && (
                    <div className="date-toolbar-custom">
                      <input
                        type="date"
                        value={customUnlockDate}
                        onChange={(e) => setCustomUnlockDate(e.target.value)}
                        min={new Date().toISOString().split('T')[0]}
                      />
                      <input
                        type="time"
                        value={customUnlockTime}
                        onChange={(e) => setCustomUnlockTime(e.target.value)}
                      />
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="date-toolbar-item" ref={expiryRef}>
              <span className="date-toolbar-label">Expires</span>
              <button
                type="button"
                className="date-toolbar-select"
                onClick={() => {
                  setExpiryOpen(!expiryOpen)
                  setUnlockOpen(false)
                }}
              >
                {expiryPreset === '15m'
                  ? '15 min'
                  : expiryPreset === '1h'
                    ? '1 hour'
                    : expiryPreset === '24h'
                      ? '24 hours'
                      : expiryPreset === '1w'
                        ? '1 week'
                        : 'Custom'}
                <span className="dropdown-arrow">▾</span>
              </button>
              {expiryOpen && (
                <div className="date-toolbar-dropdown">
                  <button
                    type="button"
                    className={expiryPreset === '15m' ? 'active' : ''}
                    onClick={() => {
                      setExpiryPreset('15m')
                      setExpiryOpen(false)
                    }}
                  >
                    15 min
                  </button>
                  <button
                    type="button"
                    className={expiryPreset === '1h' ? 'active' : ''}
                    onClick={() => {
                      setExpiryPreset('1h')
                      setExpiryOpen(false)
                    }}
                  >
                    1 hour
                  </button>
                  <button
                    type="button"
                    className={expiryPreset === '24h' ? 'active' : ''}
                    onClick={() => {
                      setExpiryPreset('24h')
                      setExpiryOpen(false)
                    }}
                  >
                    24 hours
                  </button>
                  <button
                    type="button"
                    className={expiryPreset === '1w' ? 'active' : ''}
                    onClick={() => {
                      setExpiryPreset('1w')
                      setExpiryOpen(false)
                    }}
                  >
                    1 week
                  </button>
                  <button
                    type="button"
                    className={expiryPreset === 'custom' ? 'active' : ''}
                    onClick={() => {
                      setExpiryPreset('custom')
                    }}
                  >
                    Custom
                  </button>
                  {expiryPreset === 'custom' && (
                    <div className="date-toolbar-custom">
                      <input
                        type="date"
                        value={customExpiryDate}
                        onChange={(e) => setCustomExpiryDate(e.target.value)}
                        min={unlockDate?.toISOString().split('T')[0]}
                      />
                      <input
                        type="time"
                        value={customExpiryTime}
                        onChange={(e) => setCustomExpiryTime(e.target.value)}
                      />
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <p className="security-note">Encrypted in your browser. We never see your plaintext.</p>

          {error && <div className="error-message">{error}</div>}
        </form>
      </div>
    </div>
  )
}
