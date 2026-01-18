/**
 * V2 Secret Payload Format
 *
 * All secrets use the V2 JSON format:
 * {
 *   v: 2,
 *   text: "message content",
 *   attachments: [
 *     {
 *       storage_key: "attachments/uuid",
 *       encrypted_metadata: "<base64>",  // {name, type}
 *       metadata_iv: "<base64>",
 *       metadata_auth_tag: "<base64>",
 *       blob_iv: "<base64>",
 *       blob_auth_tag: "<base64>"
 *     }
 *   ]
 * }
 *
 * Files are stored in S3, not inline. The attachments array contains
 * references and encryption parameters needed to decrypt each file.
 */

// Attachment reference stored in the payload (points to S3)
export type AttachmentRef = {
  storage_key: string
  encrypted_metadata: string // Base64 encoded
  metadata_iv: string // Base64 encoded
  metadata_auth_tag: string // Base64 encoded
  blob_iv: string // Base64 encoded
  blob_auth_tag: string // Base64 encoded
}

// V2 payload structure
export type SecretPayloadV2 = {
  v: 2
  text: string
  attachments: AttachmentRef[]
}

// Decoded attachment with decrypted metadata and raw bytes
export type DecodedAttachment = {
  name: string
  type: string
  bytes: Uint8Array
}

// Final decoded payload for display
export type DecodedPayload = {
  text: string
  attachments: DecodedAttachment[]
}

/**
 * Encode a secret payload to V2 JSON format.
 *
 * @param text - The secret message text
 * @param attachments - Array of attachment references (already uploaded to S3)
 * @returns Uint8Array of the JSON payload
 */
export function encodeSecretPayload(text: string, attachments: AttachmentRef[] = []): Uint8Array {
  const payload: SecretPayloadV2 = {
    v: 2,
    text,
    attachments,
  }
  const encoder = new TextEncoder()
  return encoder.encode(JSON.stringify(payload))
}

/**
 * Decode the text portion of a secret payload.
 *
 * This extracts just the text from the V2 JSON payload.
 * Attachment blobs must be fetched separately from S3.
 *
 * @param payloadBytes - The decrypted payload bytes
 * @returns The payload with text and attachment references
 */
export function decodeSecretPayload(payloadBytes: Uint8Array): SecretPayloadV2 {
  const decoder = new TextDecoder()
  const json = decoder.decode(payloadBytes)

  let parsed: unknown
  try {
    parsed = JSON.parse(json)
  } catch {
    throw new Error('Invalid payload: not valid JSON')
  }

  if (typeof parsed !== 'object' || parsed === null) {
    throw new Error('Invalid payload: expected object')
  }

  const obj = parsed as Record<string, unknown>

  if (obj.v !== 2) {
    throw new Error(`Unsupported payload version: ${String(obj.v)}. Expected version 2.`)
  }

  const text = typeof obj.text === 'string' ? obj.text : ''
  const attachments: AttachmentRef[] = []

  if (Array.isArray(obj.attachments)) {
    for (const att of obj.attachments) {
      if (typeof att !== 'object' || att === null) continue
      const a = att as Record<string, unknown>
      if (typeof a.storage_key !== 'string') continue

      attachments.push({
        storage_key: a.storage_key,
        encrypted_metadata: typeof a.encrypted_metadata === 'string' ? a.encrypted_metadata : '',
        metadata_iv: typeof a.metadata_iv === 'string' ? a.metadata_iv : '',
        metadata_auth_tag: typeof a.metadata_auth_tag === 'string' ? a.metadata_auth_tag : '',
        blob_iv: typeof a.blob_iv === 'string' ? a.blob_iv : '',
        blob_auth_tag: typeof a.blob_auth_tag === 'string' ? a.blob_auth_tag : '',
      })
    }
  }

  return { v: 2, text, attachments }
}

/**
 * Sanitize a filename to prevent security issues.
 *
 * - Removes path components (Unix and Windows style)
 * - Removes control characters
 * - Limits length to 255 characters
 */
export function sanitizeFilename(name: string): string {
  // Remove path components (both Unix and Windows style)
  let sanitized = name.replace(/^.*[/\\]/, '')
  // Remove null bytes and control characters (ASCII 0-31)
  // eslint-disable-next-line no-control-regex
  sanitized = sanitized.replace(/[\x00-\x1f]/g, '')
  // Limit length to 255 characters (common filesystem limit)
  if (sanitized.length > 255) {
    const ext = sanitized.lastIndexOf('.')
    if (ext > 0 && sanitized.length - ext <= 10) {
      // Preserve extension if reasonable length
      sanitized = sanitized.slice(0, 255 - (sanitized.length - ext)) + sanitized.slice(ext)
    } else {
      sanitized = sanitized.slice(0, 255)
    }
  }
  // Fallback if empty after sanitization
  return sanitized || 'attachment'
}
