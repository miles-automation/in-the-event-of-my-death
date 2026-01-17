import { describe, it, expect } from 'vitest'
import {
  bytesToHex,
  hexToBytes,
  bytesToBase64,
  base64ToBytes,
  generateRandomHex,
  generateIv,
  generateAesKey,
  exportKey,
  importKey,
  encrypt,
  decrypt,
  encryptBytes,
  decryptBytes,
  sha256,
  computePayloadHash,
  generateSecret,
  generateSecretFromBytes,
} from './crypto'

describe('crypto service', () => {
  describe('byte conversion utilities', () => {
    it('should convert bytes to hex and back', () => {
      const bytes = new Uint8Array([0, 15, 255, 128])
      const hex = bytesToHex(bytes)
      expect(hex).toBe('000fff80')

      const decoded = hexToBytes(hex)
      expect(decoded).toEqual(bytes)
    })

    it('should convert bytes to base64 and back', () => {
      const bytes = new Uint8Array([72, 101, 108, 108, 111]) // "Hello"
      const base64 = bytesToBase64(bytes)
      expect(base64).toBe('SGVsbG8=')

      const decoded = base64ToBytes(base64)
      expect(decoded).toEqual(bytes)
    })

    it('should handle large byte arrays without stack overflow', () => {
      // 1MB payload - would overflow with spread operator approach
      const largeBytes = new Uint8Array(1024 * 1024)
      for (let i = 0; i < largeBytes.length; i++) {
        largeBytes[i] = i % 256
      }

      const base64 = bytesToBase64(largeBytes)
      expect(base64.length).toBeGreaterThan(0)

      const decoded = base64ToBytes(base64)
      expect(decoded).toEqual(largeBytes)
    })
  })

  describe('random generation', () => {
    it('should generate random hex of correct length', () => {
      const hex = generateRandomHex(32)
      expect(hex).toHaveLength(64) // 32 bytes = 64 hex chars
      expect(hex).toMatch(/^[0-9a-f]+$/)
    })

    it('should generate different values each time', () => {
      const hex1 = generateRandomHex(32)
      const hex2 = generateRandomHex(32)
      expect(hex1).not.toBe(hex2)
    })

    it('should generate IV of correct length', () => {
      const iv = generateIv()
      expect(iv).toHaveLength(12) // AES-GCM standard IV is 12 bytes
    })
  })

  describe('AES key operations', () => {
    it('should generate AES key and export it', async () => {
      const key = await generateAesKey()
      expect(key.type).toBe('secret')
      expect(key.algorithm.name).toBe('AES-GCM')

      const exported = await exportKey(key)
      expect(exported).toHaveLength(32) // 256 bits = 32 bytes
    })

    it('should import key from bytes', async () => {
      const keyBytes = new Uint8Array(32).fill(42)
      const key = await importKey(keyBytes)
      expect(key.type).toBe('secret')
      expect(key.algorithm.name).toBe('AES-GCM')
    })
  })

  describe('encryption and decryption', () => {
    it('should encrypt and decrypt text correctly', async () => {
      const plaintext = 'This is a secret message'
      const key = await generateAesKey()
      const iv = generateIv()

      const encrypted = await encrypt(plaintext, key, iv)
      expect(encrypted.ciphertext).toBeTruthy()
      expect(encrypted.iv).toBeTruthy()
      expect(encrypted.authTag).toBeTruthy()

      // Export key to hex for decryption
      const keyBytes = await exportKey(key)
      const keyHex = bytesToHex(keyBytes)

      const decrypted = await decrypt(encrypted, keyHex)
      expect(decrypted).toBe(plaintext)
    })

    it('should encrypt and decrypt bytes correctly', async () => {
      const plaintextBytes = new Uint8Array([0, 1, 2, 255, 254])
      const key = await generateAesKey()
      const iv = generateIv()

      const encrypted = await encryptBytes(plaintextBytes, key, iv)
      expect(encrypted.ciphertext).toBeTruthy()

      const keyBytes = await exportKey(key)
      const keyHex = bytesToHex(keyBytes)
      const decryptedBytes = await decryptBytes(encrypted, keyHex)
      expect(decryptedBytes).toEqual(plaintextBytes)
    })

    it('should produce different ciphertext with different IV', async () => {
      const plaintext = 'Same message'
      const key = await generateAesKey()

      const encrypted1 = await encrypt(plaintext, key, generateIv())
      const encrypted2 = await encrypt(plaintext, key, generateIv())

      expect(encrypted1.ciphertext).not.toBe(encrypted2.ciphertext)
      expect(encrypted1.iv).not.toBe(encrypted2.iv)
    })

    it('should fail to decrypt with wrong key', async () => {
      const plaintext = 'Secret'
      const key = await generateAesKey()
      const wrongKey = await generateAesKey()
      const iv = generateIv()

      const encrypted = await encrypt(plaintext, key, iv)

      const wrongKeyBytes = await exportKey(wrongKey)
      const wrongKeyHex = bytesToHex(wrongKeyBytes)

      await expect(decrypt(encrypted, wrongKeyHex)).rejects.toThrow()
    })
  })

  describe('hashing', () => {
    it('should compute SHA-256 hash', async () => {
      const data = new Uint8Array([1, 2, 3, 4, 5])
      const hash = await sha256(data)
      expect(hash).toHaveLength(64) // SHA-256 = 32 bytes = 64 hex chars
      expect(hash).toMatch(/^[0-9a-f]+$/)
    })

    it('should produce same hash for same input', async () => {
      const data = new Uint8Array([1, 2, 3])
      const hash1 = await sha256(data)
      const hash2 = await sha256(data)
      expect(hash1).toBe(hash2)
    })

    it('should compute payload hash from encrypted data', async () => {
      const plaintext = 'Test'
      const key = await generateAesKey()
      const iv = generateIv()
      const encrypted = await encrypt(plaintext, key, iv)

      const hash = await computePayloadHash(encrypted)
      expect(hash).toHaveLength(64)
      expect(hash).toMatch(/^[0-9a-f]+$/)
    })
  })

  describe('generateSecret', () => {
    it('should generate complete secret with all components', async () => {
      const plaintext = 'My secret message'
      const secret = await generateSecret(plaintext)

      expect(secret.encryptionKey).toMatch(/^[0-9a-f]+$/)
      expect(secret.encryptionKey).toHaveLength(64) // 32 bytes = 64 hex chars

      expect(secret.editToken).toMatch(/^[0-9a-f]+$/)
      expect(secret.editToken).toHaveLength(64)

      expect(secret.decryptToken).toMatch(/^[0-9a-f]+$/)
      expect(secret.decryptToken).toHaveLength(64)

      expect(secret.encrypted.ciphertext).toBeTruthy()
      expect(secret.encrypted.iv).toBeTruthy()
      expect(secret.encrypted.authTag).toBeTruthy()

      expect(secret.payloadHash).toMatch(/^[0-9a-f]+$/)
      expect(secret.payloadHash).toHaveLength(64)
    })

    it('should be able to decrypt generated secret', async () => {
      const plaintext = 'My secret message'
      const secret = await generateSecret(plaintext)

      const decrypted = await decrypt(secret.encrypted, secret.encryptionKey)
      expect(decrypted).toBe(plaintext)
    })

    it('should generate secret from bytes', async () => {
      const bytes = new Uint8Array([1, 2, 3, 4])
      const secret = await generateSecretFromBytes(bytes)
      const decrypted = await decryptBytes(secret.encrypted, secret.encryptionKey)
      expect(decrypted).toEqual(bytes)
    })

    it('should generate different tokens and keys each time', async () => {
      const secret1 = await generateSecret('Same text')
      const secret2 = await generateSecret('Same text')

      expect(secret1.encryptionKey).not.toBe(secret2.encryptionKey)
      expect(secret1.editToken).not.toBe(secret2.editToken)
      expect(secret1.decryptToken).not.toBe(secret2.decryptToken)
    })
  })
})
