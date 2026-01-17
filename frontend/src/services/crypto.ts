/**
 * Web Crypto API wrapper for AES-256-GCM encryption/decryption.
 *
 * All encryption happens client-side. Keys never leave the browser.
 */

import type { EncryptedData, GeneratedSecret } from '../types'

// Helper to ensure we have a proper ArrayBuffer (not SharedArrayBuffer)
function toArrayBuffer(data: Uint8Array): ArrayBuffer {
  const buffer = data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength)
  return buffer as ArrayBuffer
}

/**
 * Convert a Uint8Array to a hex string.
 */
export function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

/**
 * Convert a hex string to a Uint8Array.
 */
export function hexToBytes(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2)
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = parseInt(hex.substring(i * 2, i * 2 + 2), 16)
  }
  return bytes
}

/**
 * Convert a Uint8Array to a base64 string.
 * Uses chunked processing to avoid call stack limits with large arrays.
 */
export function bytesToBase64(bytes: Uint8Array): string {
  const chunks: string[] = []
  const chunkSize = 0x8000 // 32KB chunks to stay well within call stack limits
  for (let i = 0; i < bytes.length; i += chunkSize) {
    chunks.push(String.fromCharCode(...bytes.subarray(i, i + chunkSize)))
  }
  return btoa(chunks.join(''))
}

/**
 * Convert a base64 string to a Uint8Array.
 */
export function base64ToBytes(base64: string): Uint8Array {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes
}

/**
 * Generate a cryptographically random 32-byte value as hex.
 */
export function generateRandomHex(byteLength: number = 32): string {
  const bytes = crypto.getRandomValues(new Uint8Array(byteLength))
  return bytesToHex(bytes)
}

/**
 * Generate a random 12-byte IV for AES-GCM.
 */
export function generateIv(): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(12))
}

/**
 * Generate a 256-bit AES key.
 */
export async function generateAesKey(): Promise<CryptoKey> {
  return crypto.subtle.generateKey(
    {
      name: 'AES-GCM',
      length: 256,
    },
    true, // extractable
    ['encrypt', 'decrypt'],
  )
}

/**
 * Export a CryptoKey to raw bytes.
 */
export async function exportKey(key: CryptoKey): Promise<Uint8Array> {
  const rawKey = await crypto.subtle.exportKey('raw', key)
  return new Uint8Array(rawKey)
}

/**
 * Import raw bytes as an AES-GCM key.
 */
export async function importKey(keyBytes: Uint8Array): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    'raw',
    toArrayBuffer(keyBytes),
    { name: 'AES-GCM', length: 256 },
    false, // not extractable when imported for decryption
    ['decrypt'],
  )
}

/**
 * Encrypt plaintext with AES-256-GCM.
 *
 * Returns the ciphertext and auth tag combined, plus the IV.
 */
export async function encrypt(
  plaintext: string,
  key: CryptoKey,
  iv: Uint8Array,
): Promise<EncryptedData> {
  const encoder = new TextEncoder()
  return encryptBytes(encoder.encode(plaintext), key, iv)
}

/**
 * Decrypt ciphertext with AES-256-GCM.
 */
export async function decrypt(encryptedData: EncryptedData, keyHex: string): Promise<string> {
  const decoder = new TextDecoder()
  const bytes = await decryptBytes(encryptedData, keyHex)
  return decoder.decode(bytes)
}

/**
 * Encrypt bytes with AES-256-GCM.
 *
 * Returns the ciphertext and auth tag combined, plus the IV.
 */
export async function encryptBytes(
  plaintextBytes: Uint8Array,
  key: CryptoKey,
  iv: Uint8Array,
): Promise<EncryptedData> {
  const ciphertextWithTag = await crypto.subtle.encrypt(
    {
      name: 'AES-GCM',
      iv: toArrayBuffer(iv),
      tagLength: 128, // 16 bytes
    },
    key,
    toArrayBuffer(plaintextBytes),
  )

  // AES-GCM appends the auth tag to the ciphertext
  // Split them: ciphertext is all but last 16 bytes, tag is last 16 bytes
  const combined = new Uint8Array(ciphertextWithTag)
  const ciphertext = combined.slice(0, combined.length - 16)
  const authTag = combined.slice(combined.length - 16)

  return {
    ciphertext: bytesToBase64(ciphertext),
    iv: bytesToBase64(iv),
    authTag: bytesToBase64(authTag),
  }
}

/**
 * Decrypt bytes with AES-256-GCM.
 */
export async function decryptBytes(
  encryptedData: EncryptedData,
  keyHex: string,
): Promise<Uint8Array> {
  const keyBytes = hexToBytes(keyHex)
  const key = await importKey(keyBytes)

  const ciphertext = base64ToBytes(encryptedData.ciphertext)
  const iv = base64ToBytes(encryptedData.iv)
  const authTag = base64ToBytes(encryptedData.authTag)

  // Combine ciphertext and auth tag (AES-GCM expects them together)
  const combined = new Uint8Array(ciphertext.length + authTag.length)
  combined.set(ciphertext)
  combined.set(authTag, ciphertext.length)

  const plaintextBuffer = await crypto.subtle.decrypt(
    {
      name: 'AES-GCM',
      iv: toArrayBuffer(iv),
      tagLength: 128,
    },
    key,
    toArrayBuffer(combined),
  )

  return new Uint8Array(plaintextBuffer)
}

/**
 * Compute SHA-256 hash of concatenated bytes.
 */
export async function sha256(data: Uint8Array): Promise<string> {
  const hashBuffer = await crypto.subtle.digest('SHA-256', toArrayBuffer(data))
  return bytesToHex(new Uint8Array(hashBuffer))
}

/**
 * Compute payload hash for PoW binding.
 * Hash of: ciphertext || iv || authTag
 */
export async function computePayloadHash(encrypted: EncryptedData): Promise<string> {
  const ciphertext = base64ToBytes(encrypted.ciphertext)
  const iv = base64ToBytes(encrypted.iv)
  const authTag = base64ToBytes(encrypted.authTag)

  const combined = new Uint8Array(ciphertext.length + iv.length + authTag.length)
  combined.set(ciphertext)
  combined.set(iv, ciphertext.length)
  combined.set(authTag, ciphertext.length + iv.length)

  return sha256(combined)
}

/**
 * Generate a complete secret with all cryptographic materials.
 *
 * This is the main entry point for creating a new secret.
 */
export async function generateSecret(plaintext: string): Promise<GeneratedSecret> {
  const encoder = new TextEncoder()
  return generateSecretFromBytes(encoder.encode(plaintext))
}

/**
 * Generate a complete secret with all cryptographic materials from raw bytes.
 */
export async function generateSecretFromBytes(
  plaintextBytes: Uint8Array,
): Promise<GeneratedSecret> {
  // Generate all random values
  const key = await generateAesKey()
  const keyBytes = await exportKey(key)
  const iv = generateIv()
  const editToken = generateRandomHex(32)
  const decryptToken = generateRandomHex(32)

  // Encrypt the payload
  const encrypted = await encryptBytes(plaintextBytes, key, iv)

  // Compute payload hash for PoW binding
  const payloadHash = await computePayloadHash(encrypted)

  return {
    encryptionKey: bytesToHex(keyBytes),
    editToken,
    decryptToken,
    encrypted,
    payloadHash,
  }
}

/**
 * Encrypted file ready for upload to S3.
 */
export type EncryptedFileUpload = {
  encrypted_blob: string // Base64
  blob_iv: string // Base64
  blob_auth_tag: string // Base64
  encrypted_metadata: string // Base64
  metadata_iv: string // Base64
  metadata_auth_tag: string // Base64
}

/**
 * Encrypt a file for upload to object storage.
 *
 * Encrypts both the file bytes and metadata (filename, type) separately,
 * using the same key but different IVs.
 *
 * @param fileBytes - Raw file bytes to encrypt
 * @param metadata - File metadata (name and type)
 * @param key - AES-GCM key to use for encryption
 * @returns Encrypted data ready for upload
 */
export async function encryptFileForUpload(
  fileBytes: Uint8Array,
  metadata: { name: string; type: string },
  key: CryptoKey,
): Promise<EncryptedFileUpload> {
  // Encrypt the file blob
  const blobIv = generateIv()
  const blobEncrypted = await encryptBytes(fileBytes, key, blobIv)

  // Encrypt the metadata
  const metadataIv = generateIv()
  const metadataJson = JSON.stringify(metadata)
  const metadataEncrypted = await encrypt(metadataJson, key, metadataIv)

  return {
    encrypted_blob: blobEncrypted.ciphertext,
    blob_iv: blobEncrypted.iv,
    blob_auth_tag: blobEncrypted.authTag,
    encrypted_metadata: metadataEncrypted.ciphertext,
    metadata_iv: metadataEncrypted.iv,
    metadata_auth_tag: metadataEncrypted.authTag,
  }
}

/**
 * Decrypt file metadata.
 *
 * @param encryptedMetadata - Base64 encoded encrypted metadata
 * @param metadataIv - Base64 encoded IV
 * @param metadataAuthTag - Base64 encoded auth tag
 * @param keyHex - Encryption key as hex string
 * @returns Decrypted metadata object with name and type
 */
export async function decryptFileMetadata(
  encryptedMetadata: string,
  metadataIv: string,
  metadataAuthTag: string,
  keyHex: string,
): Promise<{ name: string; type: string }> {
  const json = await decrypt(
    {
      ciphertext: encryptedMetadata,
      iv: metadataIv,
      authTag: metadataAuthTag,
    },
    keyHex,
  )
  const parsed = JSON.parse(json)
  return {
    name: typeof parsed.name === 'string' ? parsed.name : 'attachment',
    type: typeof parsed.type === 'string' ? parsed.type : 'application/octet-stream',
  }
}

/**
 * Decrypt a file blob downloaded from S3.
 *
 * @param encryptedBlob - Encrypted file bytes (raw, not base64)
 * @param blobIv - Base64 encoded IV
 * @param blobAuthTag - Base64 encoded auth tag
 * @param keyHex - Encryption key as hex string
 * @returns Decrypted file bytes
 */
export async function decryptFileBlob(
  encryptedBlob: Uint8Array,
  blobIv: string,
  blobAuthTag: string,
  keyHex: string,
): Promise<Uint8Array> {
  return decryptBytes(
    {
      ciphertext: bytesToBase64(encryptedBlob),
      iv: blobIv,
      authTag: blobAuthTag,
    },
    keyHex,
  )
}
