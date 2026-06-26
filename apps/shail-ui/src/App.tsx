import React, { useCallback, useEffect, useState } from 'react';
import { Routes, Route } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from './lib/queryClient';
import { Sidebar } from './components/Sidebar';
import { EvidenceRail } from './components/EvidenceRail';
import { MemoryInspector } from './components/MemoryInspector';
import { flag } from './lib/featureFlags';
import { Basecamp } from './pages/Basecamp';
import { Ascents } from './pages/Ascents';
import { Routes as RoutesPage } from './pages/Routes';
import { Horizon } from './pages/Horizon';
import { Chat } from './pages/Chat';
import { Memories } from './pages/Memories';
import { Graph } from './pages/Graph';
import { Connections } from './pages/Connections';
import { Services } from './pages/Services';
import { Settings } from './pages/Settings';
import { ExportImport } from './pages/ExportImport';
import { Graphify } from './pages/Graphify';
import { LocalFiles } from './pages/LocalFiles';
import { AuthGate } from './pages/AuthGate';
import { AnonymousSyncModal } from './components/AnonymousSyncModal';
import { getApiKey } from './auth';
import { api } from './api';

const SYNC_DISMISSED_KEY = 'shail_anon_sync_dismissed';

export function App() {
  // hydrateFromUrl() in main.tsx has already imported any ?token=... param
  // into localStorage and stripped the URL, so we only need to read storage.
  const [authed, setAuthed]         = useState<boolean>(() => !!getApiKey());
  const [showSyncModal, setShowSyncModal] = useState(false);

  const handleAuth = useCallback(async () => {
    setAuthed(true);
    // After sign-in: check if there are anonymous memories to claim.
    // Only prompt once per account (dismissed flag stored in localStorage).
    const dismissedKey = `${SYNC_DISMISSED_KEY}_${localStorage.getItem('shail_user_id') ?? 'anon'}`;
    if (localStorage.getItem(dismissedKey)) return;
    try {
      const { count } = await api.anonymousCount();
      if (count > 0) setShowSyncModal(true);
    } catch { /* ignore — don't block sign-in on network error */ }
  }, []);

  const handleSyncDone = () => {
    const dismissedKey = `${SYNC_DISMISSED_KEY}_${localStorage.getItem('shail_user_id') ?? 'anon'}`;
    localStorage.setItem(dismissedKey, '1');
    setShowSyncModal(false);
  };

  // Stay in sync when the extension's dashboard-bridge content script
  // mirrors a sign-in/sign-out from sidepanel or Options into our
  // localStorage. Re-render so Memories/Settings re-fetch with the new key.
  useEffect(() => {
    const onAuthChange = () => setAuthed(!!getApiKey());
    window.addEventListener('shail-auth-updated', onAuthChange);
    window.addEventListener('storage', onAuthChange);
    return () => {
      window.removeEventListener('shail-auth-updated', onAuthChange);
      window.removeEventListener('storage', onAuthChange);
    };
  }, []);

  // Connect to the backend WebSocket for real-time cache invalidations
  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      ws = new WebSocket('ws://localhost:8000/ws/brain');

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === 'event' && message.event_type === 'INVALIDATE_CACHE') {
            console.log('[SHAIL WS] Received cache eviction signal:', message.data);
            const keys = message.data?.keys || [];
            if (keys.includes('memories')) {
              queryClient.invalidateQueries({ queryKey: ['memories'] });
              queryClient.invalidateQueries({ queryKey: ['memory'] });
            }
            if (keys.includes('stats')) {
              window.dispatchEvent(new CustomEvent('shail-stats-updated'));
            }
            window.dispatchEvent(new CustomEvent('shail-socket-invalidation', { detail: message.data }));
          }
        } catch (e) {
          console.error('[SHAIL WS] Message error:', e);
        }
      };

      ws.onclose = () => {
        reconnectTimer = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws?.close();
      };
    }

    if (authed) {
      connect();
    }

    return () => {
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, [authed]);

  if (!authed) {
    return (
      <QueryClientProvider client={queryClient}>
        <AuthGate onAuth={handleAuth} />
      </QueryClientProvider>
    );
  }

  return (
    <QueryClientProvider client={queryClient}>
      <div style={{ display: 'flex', height: '100vh', background: '#000', color: '#fff', fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', overflow: 'hidden' }}>
        <Sidebar />
        <main style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
          <Routes>
            <Route path="/"            element={<Basecamp />} />
            <Route path="/ascents"     element={<Ascents />} />
            <Route path="/routes"      element={<RoutesPage />} />
            <Route path="/horizon"     element={<Horizon />} />
            <Route path="/chat"        element={<Chat />} />
            <Route path="/chat/:sessionId" element={<Chat />} />
            <Route path="/memories"    element={<Memories />} />
            <Route path="/memories/:id" element={<Memories />} />
            <Route path="/graph"       element={<Graph />} />
            <Route path="/connections" element={<Connections />} />
            <Route path="/services"    element={<Services />} />
            <Route path="/settings"    element={<Settings />} />
            <Route path="/export"      element={<ExportImport />} />
            <Route path="/graphify"    element={<Graphify />} />
            <Route path="/files"       element={<LocalFiles />} />
          </Routes>
        </main>
        {flag('ui_v2') && <EvidenceRail />}
      </div>
      {flag('ui_v2') && <MemoryInspector />}
      {showSyncModal && <AnonymousSyncModal onDone={handleSyncDone} />}
    </QueryClientProvider>
  );
}
