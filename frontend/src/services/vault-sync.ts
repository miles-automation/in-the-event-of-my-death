/**
 * Vault sync service — coordinates pull/push between IndexedDB and server.
 *
 * Main entrypoint: `syncVault(vaultKeyBase64)`.
 */

import type { VaultEntry } from '../types'

import { getVaultBlob, putVaultBlob, ApiError } from './api'
import { getEntries, getMeta, replaceAllEntries, setMeta } from './vault'
import {
  computeVaultId,
  decryptVaultBlob,
  deriveVaultAeadKey,
  encryptVaultBlob,
  generateSyncToken,
  type VaultBlob,
} from './vault-crypto'

const META_SYNC_TOKEN = 'syncToken'
const META_LAST_ETAG = 'lastEtag'

export interface SyncResult {
  status: 'synced' | 'created' | 'up_to_date' | 'error'
  entriesAfterSync: VaultEntry[]
  error?: string
}

/**
 * Sync vault between IndexedDB and the server.
 *
 * This is the main entrypoint. Call on app open and after local mutations.
 */
export async function syncVault(vaultKeyBase64: string): Promise<SyncResult> {
  try {
    const vaultId = await computeVaultId(vaultKeyBase64)
    const aeadKey = await deriveVaultAeadKey(vaultKeyBase64)
    const localEntries = await getEntries()
    const syncToken = await getMeta(META_SYNC_TOKEN)

    // If no syncToken, this is first sync — bootstrap
    if (!syncToken) {
      return bootstrapSync(vaultId, aeadKey, localEntries)
    }

    // Try to pull from server
    const pullResult = await getVaultBlob(vaultId, syncToken)

    if (pullResult.status === 'not_found') {
      // Server vault gone or never created — re-bootstrap
      return bootstrapSync(vaultId, aeadKey, localEntries)
    }

    // Decrypt remote blob
    const remoteBlob = await decryptVaultBlob(pullResult.ciphertext!, aeadKey, vaultId)

    // If remote has a different syncToken (rotated), update local
    if (remoteBlob.syncToken !== syncToken) {
      await setMeta(META_SYNC_TOKEN, remoteBlob.syncToken)
    }
    const activeSyncToken = remoteBlob.syncToken

    // Merge local + remote entries
    const merged = mergeEntries(localEntries, remoteBlob.entries)

    // Check if anything changed compared to remote
    const remoteKeys = new Set(remoteBlob.entries.map((e) => e.secretId))
    const mergedKeys = new Set(merged.map((e) => e.secretId))
    const hasChanges =
      merged.length !== remoteBlob.entries.length ||
      merged.some((e) => !remoteKeys.has(e.secretId)) ||
      remoteBlob.entries.some((e) => !mergedKeys.has(e.secretId)) ||
      merged.some((e) => {
        const remote = remoteBlob.entries.find((r) => r.secretId === e.secretId)
        return remote && (e.lastModified || e.createdAt) > (remote.lastModified || remote.createdAt)
      })

    if (!hasChanges) {
      // Just update local with remote state
      await replaceAllEntries(merged)
      await setMeta(META_LAST_ETAG, pullResult.etag!)
      return { status: 'up_to_date', entriesAfterSync: merged }
    }

    // Push merged state
    return pushMerged(vaultId, aeadKey, activeSyncToken, merged, pullResult.etag!)
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Sync failed'
    return { status: 'error', entriesAfterSync: await getEntries(), error: message }
  }
}

/**
 * Bootstrap: first-time sync. Creates vault on server.
 */
async function bootstrapSync(
  vaultId: string,
  aeadKey: CryptoKey,
  localEntries: VaultEntry[],
): Promise<SyncResult> {
  const syncToken = generateSyncToken()

  const blob: VaultBlob = {
    version: 1,
    syncToken,
    entries: localEntries,
    lastModified: new Date().toISOString(),
  }

  const encrypted = await encryptVaultBlob(blob, aeadKey, vaultId)

  try {
    const result = await putVaultBlob(vaultId, syncToken, encrypted, { ifNoneMatch: '*' })

    await setMeta(META_SYNC_TOKEN, syncToken)
    await setMeta(META_LAST_ETAG, result.etag)

    return { status: 'created', entriesAfterSync: localEntries }
  } catch (err) {
    // 412 = vault already exists on server (another device created it)
    // Pull from server instead
    if (err instanceof ApiError && err.status === 412) {
      // We need a syncToken to pull, but we don't have one.
      // This happens when a Phase 1 user's device has no syncToken but
      // another device already bootstrapped. The user needs to pair.
      return {
        status: 'error',
        entriesAfterSync: localEntries,
        error: 'Vault exists on another device. Use device pairing to sync.',
      }
    }
    throw err
  }
}

/**
 * Push merged entries to server.
 */
async function pushMerged(
  vaultId: string,
  aeadKey: CryptoKey,
  syncToken: string,
  merged: VaultEntry[],
  currentEtag: string,
): Promise<SyncResult> {
  const blob: VaultBlob = {
    version: 1,
    syncToken,
    entries: merged,
    lastModified: new Date().toISOString(),
  }

  const encrypted = await encryptVaultBlob(blob, aeadKey, vaultId)

  try {
    const result = await putVaultBlob(vaultId, syncToken, encrypted, { ifMatch: currentEtag })

    await replaceAllEntries(merged)
    await setMeta(META_LAST_ETAG, result.etag)

    return { status: 'synced', entriesAfterSync: merged }
  } catch (err) {
    // 409 = ETag mismatch, concurrent write from another device
    // For now, treat as error — future: auto-retry with fresh pull
    if (err instanceof ApiError && err.status === 409) {
      return {
        status: 'error',
        entriesAfterSync: merged,
        error: 'Vault was modified by another device. Please refresh.',
      }
    }
    throw err
  }
}

/**
 * Entry-level merge by secretId.
 *
 * For each secretId present in both sides, the entry with the later
 * lastModified (or createdAt as fallback) wins. Entries present in
 * only one side are always kept.
 */
export function mergeEntries(local: VaultEntry[], remote: VaultEntry[]): VaultEntry[] {
  const merged = new Map<string, VaultEntry>()

  for (const entry of remote) {
    merged.set(entry.secretId, entry)
  }

  for (const localEntry of local) {
    const remoteEntry = merged.get(localEntry.secretId)
    if (!remoteEntry) {
      merged.set(localEntry.secretId, localEntry)
    } else {
      const localTime = localEntry.lastModified || localEntry.createdAt
      const remoteTime = remoteEntry.lastModified || remoteEntry.createdAt
      if (localTime > remoteTime) {
        merged.set(localEntry.secretId, localEntry)
      }
    }
  }

  return Array.from(merged.values())
}
