import { describe, it, expect } from 'vitest'
import { decodeSecretPayload, encodeSecretPayloadV1 } from './secretPayload'

describe('secretPayload', () => {
  it('round-trips text-only payload', () => {
    const encoded = encodeSecretPayloadV1({ text: 'hello', attachments: [] })
    const decoded = decodeSecretPayload(encoded)
    expect(decoded).toEqual({ text: 'hello', attachments: [] })
  })

  it('round-trips payload with attachments', () => {
    const encoded = encodeSecretPayloadV1({
      text: 'see attached',
      attachments: [
        {
          name: 'a.txt',
          type: 'text/plain',
          bytes: new TextEncoder().encode('abc'),
        },
        {
          name: 'b.bin',
          type: 'application/octet-stream',
          bytes: new Uint8Array([0, 255, 1]),
        },
      ],
    })

    const decoded = decodeSecretPayload(encoded)
    expect(decoded.text).toBe('see attached')
    expect(decoded.attachments).toHaveLength(2)
    expect(decoded.attachments[0].name).toBe('a.txt')
    expect(decoded.attachments[0].type).toBe('text/plain')
    expect(new TextDecoder().decode(decoded.attachments[0].bytes)).toBe('abc')
    expect(decoded.attachments[1].name).toBe('b.bin')
    expect(decoded.attachments[1].type).toBe('application/octet-stream')
    expect(Array.from(decoded.attachments[1].bytes)).toEqual([0, 255, 1])
  })

  it('treats unknown payload as utf-8 text (backwards compatible)', () => {
    const bytes = new TextEncoder().encode('legacy secret')
    const decoded = decodeSecretPayload(bytes)
    expect(decoded).toEqual({ text: 'legacy secret', attachments: [] })
  })

  describe('filename sanitization', () => {
    it('removes Unix path traversal from attachment names', () => {
      const encoded = encodeSecretPayloadV1({
        text: '',
        attachments: [
          { name: '../../../etc/passwd', type: 'text/plain', bytes: new Uint8Array([1]) },
        ],
      })
      const decoded = decodeSecretPayload(encoded)
      expect(decoded.attachments[0].name).toBe('passwd')
    })

    it('removes Windows path traversal from attachment names', () => {
      const encoded = encodeSecretPayloadV1({
        text: '',
        attachments: [
          {
            name: '..\\..\\windows\\system32\\config',
            type: 'text/plain',
            bytes: new Uint8Array([1]),
          },
        ],
      })
      const decoded = decodeSecretPayload(encoded)
      expect(decoded.attachments[0].name).toBe('config')
    })

    it('removes control characters from attachment names', () => {
      const encoded = encodeSecretPayloadV1({
        text: '',
        attachments: [
          { name: 'file\x00name\x1f.txt', type: 'text/plain', bytes: new Uint8Array([1]) },
        ],
      })
      const decoded = decodeSecretPayload(encoded)
      expect(decoded.attachments[0].name).toBe('filename.txt')
    })

    it('truncates long names while preserving extension', () => {
      const longName = 'a'.repeat(300) + '.pdf'
      const encoded = encodeSecretPayloadV1({
        text: '',
        attachments: [{ name: longName, type: 'application/pdf', bytes: new Uint8Array([1]) }],
      })
      const decoded = decodeSecretPayload(encoded)
      expect(decoded.attachments[0].name.length).toBe(255)
      expect(decoded.attachments[0].name.endsWith('.pdf')).toBe(true)
    })

    it('returns fallback for empty filename after sanitization', () => {
      const encoded = encodeSecretPayloadV1({
        text: '',
        attachments: [{ name: '../', type: 'text/plain', bytes: new Uint8Array([1]) }],
      })
      const decoded = decodeSecretPayload(encoded)
      expect(decoded.attachments[0].name).toBe('attachment')
    })
  })
})
