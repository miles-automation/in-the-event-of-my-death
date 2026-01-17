export interface Challenge {
  challenge_id: string
  nonce: string
  difficulty: number
  expires_at: string
  algorithm: string
}

export interface PowProof {
  challenge_id: string
  nonce: string
  counter: number
  payload_hash: string
}

export interface SecretCreateRequest {
  ciphertext: string
  iv: string
  auth_tag: string
  unlock_at?: string // Optional when unlock_preset is provided
  unlock_preset?: 'now' | '15m' | '1h' | '24h' | '1w' // Server calculates unlock_at
  expires_at?: string // Optional when expiry_preset is provided
  expiry_preset?: '15m' | '1h' | '24h' | '1w' // Server calculates expires_at
  edit_token: string
  decrypt_token: string
  pow_proof?: PowProof
}

export interface SecretCreateResponse {
  secret_id: string
  unlock_at: string
  expires_at: string
  created_at: string
}

export interface SecretStatusResponse {
  exists: boolean
  status: 'pending' | 'available' | 'retrieved' | 'expired' | 'not_found'
  unlock_at?: string
  expires_at?: string
}

export interface SecretRetrieveResponse {
  status: string
  ciphertext?: string
  iv?: string
  auth_tag?: string
  unlock_at?: string
  expires_at?: string
  retrieved_at?: string
  message?: string
}

export interface EncryptedData {
  ciphertext: string // Base64
  iv: string // Base64
  authTag: string // Base64
}

export interface GeneratedSecret {
  encryptionKey: string // Hex
  editToken: string // Hex
  decryptToken: string // Hex
  encrypted: EncryptedData
  payloadHash: string // Hex
}

export interface ShareableLinks {
  editLink: string
  viewLink: string
}

export type VaultEntryStatus = 'pending' | 'unlocked' | 'retrieved' | 'expired'

export interface VaultEntry {
  secretId: string
  editToken: string
  createdAt: string
  unlockAt: string
  expiresAt: string
  label?: string
  recipientHint?: string
  status?: VaultEntryStatus
  lastCheckedAt?: string
}
