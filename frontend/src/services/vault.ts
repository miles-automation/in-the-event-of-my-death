import type { VaultEntry } from '../types'

import { bytesToBase64 } from './crypto'

/**
 * Client-side vault persistence using IndexedDB.
 *
 * Security note (Phase 1):
 * - Vault entries are stored unencrypted in IndexedDB and may include sensitive metadata like
 *   `editToken` and user-entered labels/hints.
 * - `vaultKey` is generated and persisted for future use, but it does not provide protection until
 *   Phase 2 encrypts entries using a key hierarchy that is not stored alongside the database.
 */
const DB_NAME = 'ieomd-vault'
const DB_VERSION = 1

const STORE_META = 'meta'
const STORE_ENTRIES = 'entries'

const VAULT_KEY_META_KEY = 'vaultKey'

type VaultMetaRecord = { key: string; value: string }

function requestToPromise<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed'))
  })
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve()
    transaction.onabort = () =>
      reject(transaction.error ?? new Error('IndexedDB transaction aborted'))
    transaction.onerror = () =>
      reject(transaction.error ?? new Error('IndexedDB transaction failed'))
  })
}

function openVaultDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)

    request.onupgradeneeded = () => {
      const db = request.result

      if (!db.objectStoreNames.contains(STORE_META)) {
        db.createObjectStore(STORE_META, { keyPath: 'key' })
      }

      if (!db.objectStoreNames.contains(STORE_ENTRIES)) {
        db.createObjectStore(STORE_ENTRIES, { keyPath: 'secretId' })
      }
    }

    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('Failed to open vault database'))
  })
}

async function withDb<T>(fn: (db: IDBDatabase) => Promise<T>): Promise<T> {
  const db = await openVaultDb()
  try {
    return await fn(db)
  } finally {
    db.close()
  }
}

async function getMetaValue(db: IDBDatabase, key: string): Promise<string | null> {
  const tx = db.transaction(STORE_META, 'readonly')
  const store = tx.objectStore(STORE_META)
  const record = await requestToPromise(store.get(key) as IDBRequest<VaultMetaRecord | undefined>)
  await transactionDone(tx)
  return record?.value ?? null
}

async function setMetaValue(db: IDBDatabase, key: string, value: string): Promise<void> {
  const tx = db.transaction(STORE_META, 'readwrite')
  const store = tx.objectStore(STORE_META)
  await requestToPromise(store.put({ key, value } satisfies VaultMetaRecord))
  await transactionDone(tx)
}

function generateVaultKeyBase64(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32))
  return bytesToBase64(bytes)
}

export async function initVault(): Promise<{ vaultKey: string }> {
  return withDb(async (db) => {
    const existing = await getMetaValue(db, VAULT_KEY_META_KEY)
    if (existing) {
      return { vaultKey: existing }
    }

    const vaultKey = generateVaultKeyBase64()
    await setMetaValue(db, VAULT_KEY_META_KEY, vaultKey)

    return { vaultKey }
  })
}

/**
 * Returns whether a vault database exists.
 *
 * On IndexedDB errors (private browsing, blocked storage, quota exceeded)
 * this returns `false` so callers can treat the vault as absent and let
 * `initVault()` handle recovery or surface a proper error later.
 */
export async function hasVault(): Promise<boolean> {
  try {
    if (typeof indexedDB.databases === 'function') {
      const databases = await indexedDB.databases()
      return databases.some((db) => db.name === DB_NAME)
    }

    return await new Promise<boolean>((resolve) => {
      const request = indexedDB.open(DB_NAME)
      let shouldResolveFalse = false

      request.onupgradeneeded = (event) => {
        const oldVersion = event.oldVersion
        if (oldVersion === 0) {
          shouldResolveFalse = true
          request.transaction?.abort()
        }
      }

      request.onsuccess = () => {
        const db = request.result
        db.close()
        resolve(true)
      }

      request.onerror = () => {
        if (shouldResolveFalse && request.error?.name === 'AbortError') {
          resolve(false)
          return
        }
        resolve(false)
      }
    })
  } catch {
    return false
  }
}

/**
 * Adds a new entry to the vault. Rejects with a `ConstraintError` if an entry
 * with the same `secretId` already exists — use `updateEntry()` to modify
 * an existing entry.
 */
export async function addEntry(entry: VaultEntry): Promise<void> {
  return withDb(async (db) => {
    const tx = db.transaction(STORE_ENTRIES, 'readwrite')
    const store = tx.objectStore(STORE_ENTRIES)
    await requestToPromise(store.add(entry))
    await transactionDone(tx)
  })
}

/** Returns a single vault entry by `secretId`, or `null` if not found. */
export async function getEntry(secretId: string): Promise<VaultEntry | null> {
  return withDb(async (db) => {
    const tx = db.transaction(STORE_ENTRIES, 'readonly')
    const store = tx.objectStore(STORE_ENTRIES)
    const entry = await requestToPromise(store.get(secretId) as IDBRequest<VaultEntry | undefined>)
    await transactionDone(tx)
    return entry ?? null
  })
}

export async function getEntries(): Promise<VaultEntry[]> {
  return withDb(async (db) => {
    const tx = db.transaction(STORE_ENTRIES, 'readonly')
    const store = tx.objectStore(STORE_ENTRIES)
    const entries = await requestToPromise(store.getAll())
    await transactionDone(tx)
    return entries
  })
}

export async function updateEntry(
  secretId: string,
  updates: Partial<Omit<VaultEntry, 'secretId'>>,
): Promise<VaultEntry> {
  return withDb(async (db) => {
    const tx = db.transaction(STORE_ENTRIES, 'readwrite')
    const store = tx.objectStore(STORE_ENTRIES)

    const existing = await requestToPromise(
      store.get(secretId) as IDBRequest<VaultEntry | undefined>,
    )
    if (!existing) {
      throw new Error(`Vault entry not found: ${secretId}`)
    }

    const updated: VaultEntry = { ...existing, ...updates, secretId }
    await requestToPromise(store.put(updated))
    await transactionDone(tx)
    return updated
  })
}

export async function deleteEntry(secretId: string): Promise<void> {
  return withDb(async (db) => {
    const tx = db.transaction(STORE_ENTRIES, 'readwrite')
    const store = tx.objectStore(STORE_ENTRIES)
    await requestToPromise(store.delete(secretId))
    await transactionDone(tx)
  })
}

// --- Phase 2: Sync helpers ---

/** Read a meta value by key. */
export async function getMeta(key: string): Promise<string | null> {
  return withDb(async (db) => getMetaValue(db, key))
}

/** Write a meta value by key. */
export async function setMeta(key: string, value: string): Promise<void> {
  return withDb(async (db) => setMetaValue(db, key, value))
}

/**
 * Replace all vault entries with the provided set.
 *
 * Used after a sync merge to persist the merged entries.
 */
export async function replaceAllEntries(entries: VaultEntry[]): Promise<void> {
  return withDb(async (db) => {
    const tx = db.transaction(STORE_ENTRIES, 'readwrite')
    const store = tx.objectStore(STORE_ENTRIES)
    await requestToPromise(store.clear())
    for (const entry of entries) {
      await requestToPromise(store.put(entry))
    }
    await transactionDone(tx)
  })
}

/**
 * Import a vaultKey from an external source (pairing or recovery).
 *
 * Overwrites any existing vaultKey. Callers should sync after import.
 */
export async function importVaultKey(vaultKeyBase64: string): Promise<void> {
  return withDb(async (db) => {
    await setMetaValue(db, VAULT_KEY_META_KEY, vaultKeyBase64)
  })
}
