import { describe, it, expect, beforeEach } from 'vitest'

import type { VaultEntry } from '../types'

import {
  addEntry,
  deleteEntry,
  getEntries,
  getEntry,
  hasVault,
  initVault,
  updateEntry,
} from './vault'

function deleteVaultDb(): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.deleteDatabase('ieomd-vault')
    request.onsuccess = () => resolve()
    request.onerror = () => reject(request.error ?? new Error('Failed to delete vault database'))
    request.onblocked = () => resolve()
  })
}

beforeEach(async () => {
  await deleteVaultDb()
})

describe('vault service', () => {
  it('hasVault returns false before init and true after init', async () => {
    await expect(hasVault()).resolves.toBe(false)
    await initVault()
    await expect(hasVault()).resolves.toBe(true)
  })

  it('initVault generates and persists a vaultKey', async () => {
    const first = await initVault()
    const second = await initVault()

    expect(first.vaultKey).toBeTruthy()
    expect(first.vaultKey).toBe(second.vaultKey)
  })

  it('adds and reads vault entries', async () => {
    await initVault()

    const entry: VaultEntry = {
      secretId: 'secret_1',
      editToken: 'edit_1',
      createdAt: new Date('2026-01-01T00:00:00Z').toISOString(),
      unlockAt: new Date('2026-01-02T00:00:00Z').toISOString(),
      expiresAt: new Date('2026-01-03T00:00:00Z').toISOString(),
      label: 'Test entry',
      recipientHint: 'For: Mom',
      status: 'pending',
      lastCheckedAt: new Date('2026-01-01T01:00:00Z').toISOString(),
    }

    await addEntry(entry)

    const entries = await getEntries()
    expect(entries).toHaveLength(1)
    expect(entries[0]).toEqual(entry)
  })

  it('getEntry returns a single entry by secretId', async () => {
    await initVault()

    const entry: VaultEntry = {
      secretId: 'secret_get',
      editToken: 'edit_get',
      createdAt: new Date('2026-01-01T00:00:00Z').toISOString(),
      unlockAt: new Date('2026-01-02T00:00:00Z').toISOString(),
      expiresAt: new Date('2026-01-03T00:00:00Z').toISOString(),
      label: 'Get test',
    }

    await addEntry(entry)
    const result = await getEntry('secret_get')
    expect(result).toEqual(entry)
  })

  it('getEntry returns null for a missing secretId', async () => {
    await initVault()
    const result = await getEntry('nonexistent')
    expect(result).toBeNull()
  })

  it('addEntry rejects on duplicate secretId', async () => {
    await initVault()

    const entry: VaultEntry = {
      secretId: 'secret_dup',
      editToken: 'edit_dup',
      createdAt: new Date('2026-01-01T00:00:00Z').toISOString(),
      unlockAt: new Date('2026-01-02T00:00:00Z').toISOString(),
      expiresAt: new Date('2026-01-03T00:00:00Z').toISOString(),
    }

    await addEntry(entry)
    await expect(addEntry({ ...entry, editToken: 'different' })).rejects.toThrow()
  })

  it('updates an entry by secretId', async () => {
    await initVault()

    const entry: VaultEntry = {
      secretId: 'secret_2',
      editToken: 'edit_2',
      createdAt: new Date('2026-01-01T00:00:00Z').toISOString(),
      unlockAt: new Date('2026-01-02T00:00:00Z').toISOString(),
      expiresAt: new Date('2026-01-03T00:00:00Z').toISOString(),
    }

    await addEntry(entry)
    const updated = await updateEntry('secret_2', { label: 'Updated label', status: 'unlocked' })

    expect(updated.label).toBe('Updated label')
    expect(updated.status).toBe('unlocked')

    const entries = await getEntries()
    expect(entries[0].label).toBe('Updated label')
    expect(entries[0].status).toBe('unlocked')
  })

  it('throws when updating a non-existent entry', async () => {
    await initVault()
    await expect(updateEntry('nonexistent', { label: 'foo' })).rejects.toThrow(
      'Vault entry not found',
    )
  })

  it('deletes an entry by secretId', async () => {
    await initVault()

    await addEntry({
      secretId: 'secret_3',
      editToken: 'edit_3',
      createdAt: new Date('2026-01-01T00:00:00Z').toISOString(),
      unlockAt: new Date('2026-01-02T00:00:00Z').toISOString(),
      expiresAt: new Date('2026-01-03T00:00:00Z').toISOString(),
    })

    await deleteEntry('secret_3')
    await expect(getEntries()).resolves.toEqual([])
  })

  it('hasVault returns false when indexedDB.databases() throws', async () => {
    const original = indexedDB.databases
    indexedDB.databases = () => Promise.reject(new Error('blocked'))
    try {
      await expect(hasVault()).resolves.toBe(false)
    } finally {
      indexedDB.databases = original
    }
  })
})
