import { describe, it, expect } from 'vitest'
import { decodeSecretPayload, encodeSecretPayload, sanitizeFilename } from './secretPayload'

describe('secretPayload V2', () => {
  describe('encodeSecretPayload', () => {
    it('encodes text-only payload', () => {
      const encoded = encodeSecretPayload('hello world')
      const decoder = new TextDecoder()
      const json = JSON.parse(decoder.decode(encoded))
      expect(json).toEqual({
        v: 2,
        text: 'hello world',
        attachments: [],
      })
    })

    it('encodes payload with attachment references', () => {
      const encoded = encodeSecretPayload('see files', [
        {
          storage_key: 'attachments/abc123',
          encrypted_metadata: 'bWV0YQ==',
          metadata_iv: 'aXYxMjM0NTY3ODkw',
          metadata_auth_tag: 'dGFn',
          blob_iv: 'Ymxvx2l2',
          blob_auth_tag: 'Ymxvx3RhZw==',
        },
      ])
      const decoder = new TextDecoder()
      const json = JSON.parse(decoder.decode(encoded))
      expect(json.v).toBe(2)
      expect(json.text).toBe('see files')
      expect(json.attachments).toHaveLength(1)
      expect(json.attachments[0].storage_key).toBe('attachments/abc123')
    })
  })

  describe('decodeSecretPayload', () => {
    it('decodes text-only payload', () => {
      const encoded = encodeSecretPayload('hello')
      const decoded = decodeSecretPayload(encoded)
      expect(decoded).toEqual({
        v: 2,
        text: 'hello',
        attachments: [],
      })
    })

    it('decodes payload with attachment references', () => {
      const attachments = [
        {
          storage_key: 'attachments/file1',
          encrypted_metadata: 'ZW5jcnlwdGVk',
          metadata_iv: 'aXZfZGF0YQ==',
          metadata_auth_tag: 'dGFnX2RhdGE=',
          blob_iv: 'YmxvYl9pdg==',
          blob_auth_tag: 'YmxvYl90YWc=',
        },
        {
          storage_key: 'attachments/file2',
          encrypted_metadata: 'ZW5jMg==',
          metadata_iv: 'aXYy',
          metadata_auth_tag: 'dGFnMg==',
          blob_iv: 'Ymxvx2l2Mg==',
          blob_auth_tag: 'Ymxvx3RhZzI=',
        },
      ]
      const encoded = encodeSecretPayload('message', attachments)
      const decoded = decodeSecretPayload(encoded)

      expect(decoded.v).toBe(2)
      expect(decoded.text).toBe('message')
      expect(decoded.attachments).toHaveLength(2)
      expect(decoded.attachments[0].storage_key).toBe('attachments/file1')
      expect(decoded.attachments[1].storage_key).toBe('attachments/file2')
    })

    it('throws error for invalid JSON', () => {
      const bytes = new TextEncoder().encode('not valid json {{{')
      expect(() => decodeSecretPayload(bytes)).toThrow('Invalid payload: not valid JSON')
    })

    it('throws error for wrong version', () => {
      const payload = JSON.stringify({ v: 1, text: 'old format' })
      const bytes = new TextEncoder().encode(payload)
      expect(() => decodeSecretPayload(bytes)).toThrow(
        'Unsupported payload version: 1. Expected version 2.',
      )
    })

    it('throws error for missing version', () => {
      const payload = JSON.stringify({ text: 'no version' })
      const bytes = new TextEncoder().encode(payload)
      expect(() => decodeSecretPayload(bytes)).toThrow(
        'Unsupported payload version: undefined. Expected version 2.',
      )
    })

    it('handles missing text gracefully', () => {
      const payload = JSON.stringify({ v: 2, attachments: [] })
      const bytes = new TextEncoder().encode(payload)
      const decoded = decodeSecretPayload(bytes)
      expect(decoded.text).toBe('')
    })

    it('handles missing attachments gracefully', () => {
      const payload = JSON.stringify({ v: 2, text: 'no attachments field' })
      const bytes = new TextEncoder().encode(payload)
      const decoded = decodeSecretPayload(bytes)
      expect(decoded.attachments).toEqual([])
    })

    it('skips malformed attachment entries', () => {
      const payload = JSON.stringify({
        v: 2,
        text: 'test',
        attachments: [
          {
            storage_key: 'valid/key',
            encrypted_metadata: 'x',
            metadata_iv: 'y',
            metadata_auth_tag: 'z',
            blob_iv: 'a',
            blob_auth_tag: 'b',
          },
          null,
          { missing_storage_key: true },
          'not an object',
          { storage_key: 'another/valid', encrypted_metadata: 'm' },
        ],
      })
      const bytes = new TextEncoder().encode(payload)
      const decoded = decodeSecretPayload(bytes)
      expect(decoded.attachments).toHaveLength(2)
      expect(decoded.attachments[0].storage_key).toBe('valid/key')
      expect(decoded.attachments[1].storage_key).toBe('another/valid')
    })
  })

  describe('sanitizeFilename', () => {
    it('removes Unix path traversal', () => {
      expect(sanitizeFilename('../../../etc/passwd')).toBe('passwd')
      expect(sanitizeFilename('/absolute/path/file.txt')).toBe('file.txt')
    })

    it('removes Windows path traversal', () => {
      expect(sanitizeFilename('..\\..\\windows\\system32\\config')).toBe('config')
      expect(sanitizeFilename('C:\\Users\\file.txt')).toBe('file.txt')
    })

    it('removes control characters', () => {
      expect(sanitizeFilename('file\x00name\x1f.txt')).toBe('filename.txt')
    })

    it('truncates long names while preserving extension', () => {
      const longName = 'a'.repeat(300) + '.pdf'
      const result = sanitizeFilename(longName)
      expect(result.length).toBe(255)
      expect(result.endsWith('.pdf')).toBe(true)
    })

    it('returns fallback for empty filename after sanitization', () => {
      expect(sanitizeFilename('../')).toBe('attachment')
      expect(sanitizeFilename('')).toBe('attachment')
      expect(sanitizeFilename('\x00\x01\x02')).toBe('attachment')
    })
  })
})
