/**
 * scroll-pump-store.ts — IndexedDB-backed durable buffer for scroll-pump captures.
 *
 * During a retroactive "Capture Full Session" scroll-pump, we write each
 * newly-discovered turn to this IndexedDB store as a crash-safe buffer.
 * If the tab crashes or the extension reloads mid-pump, the buffered turns
 * survive and can be assembled into a bulk capture on the next attempt.
 *
 * Schema: { conversationId, turnIndex, userText, assistantText, fingerprint, timestamp }
 * Dedup: fingerprint uniqueness — if a turn with the same fingerprint already
 * exists for a conversationId, the insert is silently skipped.
 */

const DB_NAME    = 'shail-scroll-pump';
const DB_VERSION = 1;
const STORE_NAME = 'turns';

export interface ScrollPumpTurn {
  conversationId: string;
  turnIndex: number;
  userText: string;
  assistantText: string;
  fingerprint: string;
  timestamp: number;
}

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: ['conversationId', 'turnIndex'] });
        store.createIndex('by_conversation', 'conversationId', { unique: false });
        store.createIndex('by_fingerprint', ['conversationId', 'fingerprint'], { unique: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror   = () => reject(req.error);
  });
}

/**
 * Append a turn to the buffer. Deduplicates by fingerprint — if a turn
 * with the same (conversationId, fingerprint) already exists, the write
 * is silently skipped (returns false). Returns true on successful insert.
 */
export async function appendTurn(turn: ScrollPumpTurn): Promise<boolean> {
  const db = await openDB();
  return new Promise<boolean>((resolve) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);

    // Check fingerprint uniqueness via the index
    const fpIdx = store.index('by_fingerprint');
    const fpReq = fpIdx.get([turn.conversationId, turn.fingerprint]);

    fpReq.onsuccess = () => {
      if (fpReq.result) {
        // Duplicate — skip silently
        resolve(false);
        return;
      }
      // Not a duplicate — insert
      const addReq = store.add(turn);
      addReq.onsuccess = () => resolve(true);
      addReq.onerror = () => resolve(false); // key collision on turnIndex — skip
    };
    fpReq.onerror = () => resolve(false);
  });
}

/**
 * Retrieve all buffered turns for a conversation, sorted by turnIndex.
 */
export async function getTurns(conversationId: string): Promise<ScrollPumpTurn[]> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const idx = tx.objectStore(STORE_NAME).index('by_conversation');
    const req = idx.getAll(conversationId);
    req.onsuccess = () => {
      const turns = (req.result as ScrollPumpTurn[]);
      turns.sort((a, b) => a.turnIndex - b.turnIndex);
      resolve(turns);
    };
    req.onerror = () => reject(req.error);
  });
}

/**
 * Clear all buffered turns for a conversation (after successful bulk send).
 */
export async function clearConversation(conversationId: string): Promise<void> {
  const db = await openDB();
  const turns = await getTurns(conversationId);
  if (turns.length === 0) return;
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    for (const turn of turns) {
      store.delete([turn.conversationId, turn.turnIndex]);
    }
    tx.oncomplete = () => resolve();
    tx.onerror    = () => reject(tx.error);
  });
}

/**
 * Count of buffered turns across all conversations.
 */
export async function size(): Promise<number> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const req = tx.objectStore(STORE_NAME).count();
    req.onsuccess = () => resolve(req.result);
    req.onerror   = () => reject(req.error);
  });
}
