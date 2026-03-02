/**
 * Vault-specific crypto operations.
 *
 * HKDF key derivation for vault encryption, and password-wrapping
 * for device pairing links.
 */

import type { VaultEntry } from '../types'

import { base64ToBytes, bytesToBase64, bytesToHex } from './crypto'

const HKDF_INFO = new TextEncoder().encode('vault:aead:v1')
const VAULT_SCHEMA_VERSION = 1

/** Helper to ensure a proper ArrayBuffer (not a view into a SharedArrayBuffer). */
function toArrayBuffer(data: Uint8Array): ArrayBuffer {
  return data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) as ArrayBuffer
}

/**
 * Derive vaultAeadKey from vaultKey using HKDF (RFC 5869).
 *
 * vaultKey (base64) -> HKDF-SHA256 -> AES-256-GCM CryptoKey
 */
export async function deriveVaultAeadKey(vaultKeyBase64: string): Promise<CryptoKey> {
  const vaultKeyBytes = base64ToBytes(vaultKeyBase64)

  const ikm = await crypto.subtle.importKey('raw', toArrayBuffer(vaultKeyBytes), 'HKDF', false, [
    'deriveKey',
  ])

  return crypto.subtle.deriveKey(
    {
      name: 'HKDF',
      hash: 'SHA-256',
      salt: new Uint8Array(0),
      info: HKDF_INFO,
    },
    ikm,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  )
}

/**
 * Compute vaultId = SHA-256(vaultKey) as hex string.
 */
export async function computeVaultId(vaultKeyBase64: string): Promise<string> {
  const vaultKeyBytes = base64ToBytes(vaultKeyBase64)
  const hashBuffer = await crypto.subtle.digest('SHA-256', toArrayBuffer(vaultKeyBytes))
  return bytesToHex(new Uint8Array(hashBuffer))
}

/**
 * Generate a random 256-bit syncToken as hex string.
 */
export function generateSyncToken(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32))
  return bytesToHex(bytes)
}

/** The plaintext structure encrypted inside the vault blob. */
export interface VaultBlob {
  version: number
  syncToken: string
  entries: VaultEntry[]
  lastModified: string
}

/**
 * Encrypt a VaultBlob using vaultAeadKey.
 *
 * AAD includes vaultId + schema version to prevent cross-vault substitution.
 * Wire format: [1B version][12B IV][ciphertext+tag]
 */
export async function encryptVaultBlob(
  blob: VaultBlob,
  aeadKey: CryptoKey,
  vaultId: string,
): Promise<string> {
  const plaintext = new TextEncoder().encode(JSON.stringify(blob))
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const aad = new TextEncoder().encode(`${vaultId}:${VAULT_SCHEMA_VERSION}`)

  const ciphertextWithTag = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: toArrayBuffer(iv), additionalData: toArrayBuffer(aad), tagLength: 128 },
    aeadKey,
    toArrayBuffer(plaintext),
  )

  const packed = new Uint8Array(1 + 12 + ciphertextWithTag.byteLength)
  packed[0] = VAULT_SCHEMA_VERSION
  packed.set(iv, 1)
  packed.set(new Uint8Array(ciphertextWithTag), 13)

  return bytesToBase64(packed)
}

/**
 * Decrypt a vault blob back to VaultBlob.
 */
export async function decryptVaultBlob(
  ciphertextBase64: string,
  aeadKey: CryptoKey,
  vaultId: string,
): Promise<VaultBlob> {
  const packed = base64ToBytes(ciphertextBase64)

  const version = packed[0]
  if (version !== VAULT_SCHEMA_VERSION) {
    throw new Error(`Unsupported vault schema version: ${version}`)
  }

  const iv = packed.slice(1, 13)
  const ciphertextWithTag = packed.slice(13)
  const aad = new TextEncoder().encode(`${vaultId}:${version}`)

  const plaintext = await crypto.subtle.decrypt(
    {
      name: 'AES-GCM',
      iv: toArrayBuffer(iv),
      additionalData: toArrayBuffer(aad),
      tagLength: 128,
    },
    aeadKey,
    toArrayBuffer(ciphertextWithTag),
  )

  return JSON.parse(new TextDecoder().decode(plaintext))
}

/**
 * Derive a password-wrapping key for device pairing (PBKDF2).
 *
 * Uses 600,000 iterations per OWASP 2023 recommendation for PBKDF2-SHA256.
 */
export async function derivePasswordKey(password: string, salt: Uint8Array): Promise<CryptoKey> {
  const keyMaterial = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(password),
    'PBKDF2',
    false,
    ['deriveKey'],
  )

  return crypto.subtle.deriveKey(
    {
      name: 'PBKDF2',
      salt: toArrayBuffer(salt),
      iterations: 600_000,
      hash: 'SHA-256',
    },
    keyMaterial,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  )
}

/**
 * Encrypt vaultKey with a password for pairing link.
 *
 * Returns encrypted data and salt, both as base64.
 */
export async function wrapVaultKeyWithPassword(
  vaultKeyBase64: string,
  password: string,
): Promise<{ encrypted: string; salt: string }> {
  const salt = crypto.getRandomValues(new Uint8Array(16))
  const wrappingKey = await derivePasswordKey(password, salt)
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const plaintext = new TextEncoder().encode(vaultKeyBase64)

  const ciphertext = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: toArrayBuffer(iv), tagLength: 128 },
    wrappingKey,
    toArrayBuffer(plaintext),
  )

  const packed = new Uint8Array(12 + ciphertext.byteLength)
  packed.set(iv, 0)
  packed.set(new Uint8Array(ciphertext), 12)

  return {
    encrypted: bytesToBase64(packed),
    salt: bytesToBase64(salt),
  }
}

/**
 * Decrypt vaultKey from a pairing link.
 */
export async function unwrapVaultKeyWithPassword(
  encryptedBase64: string,
  saltBase64: string,
  password: string,
): Promise<string> {
  const salt = base64ToBytes(saltBase64)
  const wrappingKey = await derivePasswordKey(password, salt)

  const packed = base64ToBytes(encryptedBase64)
  const iv = packed.slice(0, 12)
  const ciphertextWithTag = packed.slice(12)

  const plaintext = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: toArrayBuffer(iv), tagLength: 128 },
    wrappingKey,
    toArrayBuffer(ciphertextWithTag),
  )

  return new TextDecoder().decode(plaintext)
}
