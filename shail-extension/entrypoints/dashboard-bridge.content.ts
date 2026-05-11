/**
 * dashboard-bridge.content.ts
 *
 * Bridges auth credentials between the dashboard (localStorage on
 * localhost:8000) and the extension (browser.storage.sync). Without this,
 * signing in on one surface leaves the other surface logged out, even
 * though they hit the same backend account.
 *
 * Behaviour:
 *  - On load: read both sides. The newest non-empty key wins. Mirror it
 *    to the other side so both surfaces see the same authenticated user.
 *  - On dashboard sign-in (storage event from same tab): mirror localStorage
 *    -> extension storage.
 *  - On extension sign-in (browser.storage.onChanged): mirror extension
 *    storage -> page localStorage and dispatch a 'shail-auth-updated'
 *    CustomEvent so the dashboard can re-fetch user data without a reload.
 */

const KEYS = ['shail_api_key', 'shail_user_id', 'shail_email', 'shail_name'] as const;
type AuthKey = typeof KEYS[number];

export default defineContentScript({
  matches: [
    'http://localhost:8000/*',
    'http://127.0.0.1:8000/*',
  ],
  runAt: 'document_start',

  async main(ctx) {
    const readPage = (): Record<AuthKey, string | null> => {
      const out = {} as Record<AuthKey, string | null>;
      for (const k of KEYS) out[k] = window.localStorage.getItem(k);
      return out;
    };

    const writePage = (vals: Partial<Record<AuthKey, string | null>>) => {
      for (const [k, v] of Object.entries(vals)) {
        if (v === null || v === undefined || v === '') {
          window.localStorage.removeItem(k);
        } else {
          window.localStorage.setItem(k, v);
        }
      }
      window.dispatchEvent(new CustomEvent('shail-auth-updated'));
    };

    const readExt = async (): Promise<Record<AuthKey, string | null>> => {
      const raw = await browser.storage.sync.get(KEYS as unknown as string[]);
      const out = {} as Record<AuthKey, string | null>;
      for (const k of KEYS) out[k] = (raw[k] as string | undefined) ?? null;
      return out;
    };

    const writeExt = async (vals: Partial<Record<AuthKey, string | null>>) => {
      const toSet: Record<string, string> = {};
      const toRemove: string[] = [];
      for (const [k, v] of Object.entries(vals)) {
        if (v === null || v === undefined || v === '') toRemove.push(k);
        else toSet[k] = v;
      }
      if (Object.keys(toSet).length) await browser.storage.sync.set(toSet);
      if (toRemove.length) await browser.storage.sync.remove(toRemove);
    };

    // Initial sync: pick the side that has an api_key. If both have one,
    // page (dashboard) wins because the user just logged in there.
    try {
      const page = readPage();
      const ext = await readExt();

      if (page.shail_api_key && page.shail_api_key !== ext.shail_api_key) {
        await writeExt(page);
      } else if (ext.shail_api_key && !page.shail_api_key) {
        writePage(ext);
      } else if (!ext.shail_api_key && !page.shail_api_key) {
        // both empty — nothing to do
      }
    } catch {
      // swallow — the bridge must never crash the page
    }

    // ── Re-entrancy guard ──────────────────────────────────────────────
    // Without this flag, the two listeners below create an infinite loop:
    //   storage.onChanged → writePage() → dispatches 'shail-auth-updated'
    //   → onLocalUpdate() → writeExt() → triggers storage.onChanged → …
    // The flag breaks the cycle: if we're already syncing, skip.
    let _syncing = false;

    // Watch extension storage for changes (e.g. user signs in via Options
    // page or sidepanel). Mirror to localStorage and notify the dashboard.
    const offStorage = browser.storage.onChanged.addListener((changes, area) => {
      if (area !== 'sync') return;
      if (_syncing) return;
      const updates: Partial<Record<AuthKey, string | null>> = {};
      let touched = false;
      for (const k of KEYS) {
        if (k in changes) {
          updates[k] = (changes[k].newValue as string | null | undefined) ?? null;
          touched = true;
        }
      }
      if (touched) {
        _syncing = true;
        writePage(updates);
        _syncing = false;
      }
    });

    // Watch page-side localStorage changes. The 'storage' event only fires
    // for OTHER tabs/windows on the same origin, so for same-tab sign-ins
    // we rely on the dashboard explicitly dispatching 'shail-auth-updated'
    // (done in apps/shail-ui/src/auth.ts) — we listen for that here too.
    const onStorageEvt = async (e: StorageEvent) => {
      if (!e.key || !(KEYS as readonly string[]).includes(e.key)) return;
      if (_syncing) return;
      _syncing = true;
      const vals = readPage();
      await writeExt(vals);
      _syncing = false;
    };
    window.addEventListener('storage', onStorageEvt);

    const onLocalUpdate = async () => {
      if (_syncing) return;
      _syncing = true;
      const vals = readPage();
      await writeExt(vals);
      _syncing = false;
    };
    window.addEventListener('shail-auth-updated', onLocalUpdate as EventListener);

    ctx.onInvalidated(() => {
      window.removeEventListener('storage', onStorageEvt);
      window.removeEventListener('shail-auth-updated', onLocalUpdate as EventListener);
      // browser.storage.onChanged.addListener returns void in WXT/Mozilla
      // typings; we rely on the listener being detached when the content
      // script is invalidated.
      void offStorage;
    });
  },
});
