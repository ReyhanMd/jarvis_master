import React, { useEffect, useRef, useState } from 'react';
import { api, MemoryRecord, SOURCE_COLOR, SOURCE_LABEL } from '../api';
import { ImportDropzone } from '../components/phase-c/ImportDropzone';

export function ExportImport() {
  const [records, setRecords]       = useState<MemoryRecord[]>([]);
  const [loading, setLoading]       = useState(true);
  const [selected, setSelected]     = useState<Set<string>>(new Set());
  const [importing, setImporting]   = useState(false);
  const [importResult, setImportResult] = useState<{ imported: number; skipped: number } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const apiKey = localStorage.getItem('shail_api_key') ?? '';

  useEffect(() => {
    api.search({ query: '', k: 500 })
      .then(r => { setRecords(r.items); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  function toggleSelect(id: string) {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (selected.size === records.length) setSelected(new Set());
    else setSelected(new Set(records.map(r => r.id)));
  }

  function handleExport() {
    const toExport = selected.size > 0 ? records.filter(r => selected.has(r.id)) : records;
    const url = new URL(`http://localhost:8000/browser/export`);
    // Use auth header via fetch + blob download
    fetch(url.toString(), { headers: { Authorization: `Bearer ${apiKey}` } })
      .then(res => res.blob())
      .then(blob => {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'shail-export.json';
        a.click();
      });
  }

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setImportResult(null);
    try {
      const text = await file.text();
      const data: MemoryRecord[] = JSON.parse(text);
      const result = await api.import(data);
      setImportResult(result);
      // Refresh list
      const resp = await api.search({ query: '', k: 500 });
      setRecords(resp.items);
    } catch (err) {
      setImportResult({ imported: 0, skipped: -1 });
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', padding: '40px 48px 0' }}>
      <h1 style={{ margin: '0 0 8px', fontSize: 22, fontWeight: 500, color: '#fff', letterSpacing: '-0.4px' }}>Export / Import</h1>

      {/* Actions row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 32, marginTop: 24 }}>
        <button
          onClick={handleExport}
          style={{ padding: '9px 20px', borderRadius: 7, fontSize: 12, fontWeight: 500, cursor: 'pointer', background: '#0d0d0d', border: '1px solid #1e1e1e', color: '#888', transition: 'color 0.1s' }}
          onMouseEnter={e => (e.currentTarget.style.color = '#fff')}
          onMouseLeave={e => (e.currentTarget.style.color = '#888')}
        >
          ↓ Export {selected.size > 0 ? `${selected.size} selected` : 'all'} as JSON
        </button>
        <label style={{ padding: '9px 20px', borderRadius: 7, fontSize: 12, fontWeight: 500, cursor: 'pointer', background: '#0d0d0d', border: '1px solid #1e1e1e', color: '#888', transition: 'color 0.1s', userSelect: 'none' }}
          onMouseEnter={e => (e.currentTarget.style.color = '#fff')}
          onMouseLeave={e => (e.currentTarget.style.color = '#888')}
        >
          ↑ Import JSON
          <input ref={fileRef} type="file" accept=".json" onChange={handleImport} style={{ display: 'none' }} />
        </label>
        {importing && <span style={{ fontSize: 12, color: '#333' }}>Importing…</span>}
        {importResult && (
          <span style={{ fontSize: 12, color: importResult.skipped === -1 ? '#ef4444' : '#22c55e' }}>
            {importResult.skipped === -1 ? 'Import failed — invalid file' : `Imported ${importResult.imported}, skipped ${importResult.skipped} duplicates`}
          </span>
        )}
      </div>

      {/* Phase C Sprint 4 — import chats from external AI tools */}
      <div style={{ marginBottom: 32 }}>
        <div style={{ fontSize: 11, color: '#666', letterSpacing: '0.1em', fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace', marginBottom: 8 }}>
          IMPORT EXTERNAL CHAT EXPORTS
        </div>
        <ImportDropzone />
      </div>

      {/* Select all */}
      {records.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <button onClick={toggleAll} style={{ fontSize: 11, color: '#444', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
            {selected.size === records.length ? 'Deselect all' : `Select all (${records.length})`}
          </button>
        </div>
      )}

      {/* List */}
      <div style={{ flex: 1, overflowY: 'auto', paddingBottom: 48, display: 'flex', flexDirection: 'column', gap: 1 }}>
        {loading && <div style={{ marginTop: 60, textAlign: 'center', color: '#252525', fontSize: 13 }}>Loading…</div>}
        {!loading && records.length === 0 && <div style={{ marginTop: 60, textAlign: 'center', color: '#252525', fontSize: 13 }}>No memories to export</div>}
        {records.map(r => {
          const isSel = selected.has(r.id);
          const color = SOURCE_COLOR[r.sourceApp] ?? '#444';
          const ts = new Date(r.timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
          return (
            <div
              key={r.id}
              onClick={() => toggleSelect(r.id)}
              style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', borderRadius: 6, cursor: 'pointer', background: isSel ? '#0f0f0f' : 'transparent', border: `1px solid ${isSel ? '#1e1e1e' : 'transparent'}`, transition: 'all 0.1s' }}
            >
              <input type="checkbox" checked={isSel} onChange={() => {}} style={{ accentColor: '#ef4444', flexShrink: 0 }} />
              <span style={{ fontSize: 10, fontWeight: 600, color, background: color + '18', border: `1px solid ${color}28`, borderRadius: 3, padding: '2px 6px', flexShrink: 0 }}>
                {SOURCE_LABEL[r.sourceApp] ?? r.sourceApp}
              </span>
              <span style={{ flex: 1, fontSize: 12, color: '#777', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.title || r.sourceUrl}</span>
              <span style={{ fontSize: 11, color: '#2a2a2a', flexShrink: 0 }}>{ts}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
