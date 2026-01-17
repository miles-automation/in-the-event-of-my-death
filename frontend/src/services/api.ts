/**
 * API client for the backend.
 */

import type {
  Challenge,
  SecretCreateRequest,
  SecretCreateResponse,
  SecretStatusResponse,
  SecretRetrieveResponse,
} from '../types'

import { resolveApiBaseUrl } from './apiBase'

const API_BASE = resolveApiBaseUrl({
  apiUrl: import.meta.env.VITE_API_URL,
  isDev: import.meta.env.DEV,
  origin: window.location.origin,
})

class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = 'An error occurred'
    try {
      const data = await response.json()
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {
      detail = response.statusText
    }
    throw new ApiError(response.status, detail)
  }
  return response.json()
}

/**
 * Request a proof-of-work challenge.
 */
export async function requestChallenge(
  payloadHash: string,
  ciphertextSize: number,
): Promise<Challenge> {
  const response = await fetch(`${API_BASE}/challenges`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      payload_hash: payloadHash,
      ciphertext_size: ciphertextSize,
    }),
  })
  return handleResponse<Challenge>(response)
}

/**
 * Create a new secret.
 */
export async function createSecret(
  request: SecretCreateRequest,
  options?: { capabilityToken?: string },
): Promise<SecretCreateResponse> {
  const response = await fetch(`${API_BASE}/secrets`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(options?.capabilityToken ? { 'X-Capability-Token': options.capabilityToken } : {}),
    },
    body: JSON.stringify(request),
  })
  return handleResponse<SecretCreateResponse>(response)
}

/**
 * Check the status of a secret without triggering one-time deletion.
 */
export async function getSecretStatus(decryptToken: string): Promise<SecretStatusResponse> {
  const response = await fetch(`${API_BASE}/secrets/status`, {
    headers: { Authorization: `Bearer ${decryptToken}` },
  })
  return handleResponse<SecretStatusResponse>(response)
}

/**
 * Check the status of a secret using the edit token.
 * Used by the edit page to display current unlock date.
 */
export async function getEditSecretStatus(editToken: string): Promise<SecretStatusResponse> {
  const response = await fetch(`${API_BASE}/secrets/edit/status`, {
    headers: { Authorization: `Bearer ${editToken}` },
  })
  return handleResponse<SecretStatusResponse>(response)
}

/**
 * Retrieve a secret's encrypted content.
 * This is a ONE-TIME operation after unlock.
 */
export async function retrieveSecret(decryptToken: string): Promise<SecretRetrieveResponse> {
  const response = await fetch(`${API_BASE}/secrets/retrieve`, {
    headers: { Authorization: `Bearer ${decryptToken}` },
  })

  // Handle 403 (not yet unlocked) specially
  if (response.status === 403) {
    const data = await response.json()
    return {
      status: 'pending',
      unlock_at: data.detail?.unlock_at,
      message: data.detail?.message || 'Secret not yet available',
    }
  }

  // Handle 410 (already retrieved or expired)
  if (response.status === 410) {
    const data = await response.json()
    const detail = data.detail

    // Check if it's an expired secret
    if (detail?.status === 'expired') {
      return {
        status: 'expired',
        expires_at: detail.expires_at,
        message: detail.message || 'This secret has expired',
      }
    }

    // Default to retrieved
    return {
      status: 'retrieved',
      message: detail?.message || 'This secret has already been retrieved',
    }
  }

  return handleResponse<SecretRetrieveResponse>(response)
}

/**
 * Update the unlock and expiry dates of a secret.
 */
export async function updateSecretDates(
  editToken: string,
  newUnlockAt: string,
  newExpiresAt: string,
): Promise<{ secret_id: string; unlock_at: string; expires_at: string }> {
  const response = await fetch(`${API_BASE}/secrets/edit`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${editToken}`,
    },
    body: JSON.stringify({ unlock_at: newUnlockAt, expires_at: newExpiresAt }),
  })
  return handleResponse(response)
}

/**
 * Submit user feedback.
 */
export async function submitFeedback(
  message: string,
  email?: string,
): Promise<{ success: boolean; message: string }> {
  const response = await fetch(`${API_BASE}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, email: email || null }),
  })
  return handleResponse(response)
}

export { ApiError }
