import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import * as d3 from 'd3';
import { api, GraphApiDocument, GraphApiMemory, SOURCE_COLOR, SOURCE_LABEL } from '../api';
import { MemoryCard } from '../components/MemoryCard';
import { useUIStore } from '../stores/ui';
import { flag } from '../lib/featureFlags';

const SOURCES = ['chatgpt', 'claude', 'gemini', 'perplexity', 'web'] as const;

function hashToUnit(str: string): number {
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = (Math.imul(31, h) + str.charCodeAt(i)) | 0;
  }
  return ((h >>> 0) % 10000) / 10000;
}

interface Node extends d3.SimulationNodeDatum {
  id: string;
  isDoc: boolean;
  label: string;
  sourceApp?: string;
  importance?: number;
  isExpiring?: boolean;
}

interface Link {
  id: string;
  source: string | Node;
  target: string | Node;
  type: string;
  weight: number;
}

const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;

export function Graph() {
  const svgRef = useRef<SVGSVGElement>(null);
  const [filter, setFilter] = useState('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showEvidence, setShowEvidence] = useState(false);
  const simRef = useRef<d3.Simulation<Node, Link> | null>(null);

  const citedIds = useUIStore(s => s.lastAnswerCitations)
    .filter(c => c.type === 'memory')
    .map(c => (c as { id: string }).id);

  const { data, isLoading, error } = useQuery({
    queryKey: ['memories', 'graph'],
    queryFn: () => api.memoryGraph(),
    staleTime: 2 * 60_000,
  });

  const selectedMemory = useQuery({
    queryKey: ['memories', 'detail', selectedId],
    queryFn: () => api.getMemory(selectedId!),
    enabled: !!selectedId && !selectedId.startsWith('doc_'),
    staleTime: 2 * 60_000,
  });

  const { nodes, edges } = useMemo(() => {
    const rawDocs = data?.documents ?? [];
    const docs = filter === 'all'
      ? rawDocs
      : rawDocs.filter(d => d.documentType === filter);

    if (docs.length === 0) return { nodes: [], edges: [] };

    const nodes: Node[] = [];
    const links: Link[] = [];

    const cx = window.innerWidth / 2;
    const cy = window.innerHeight / 2;
    const docCount = docs.length;
    const spiralScale = Math.sqrt(docCount) * 60;
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));

    for (let docIdx = 0; docIdx < docCount; docIdx++) {
      const doc = docs[docIdx];
      const angle = docIdx * goldenAngle;
      const radius = spiralScale * Math.sqrt((docIdx + 1) / docCount);
      const docX = cx + Math.cos(angle) * radius;
      const docY = cy + Math.sin(angle) * radius;

      nodes.push({
        id: doc.id,
        isDoc: true,
        label: doc.title || doc.id,
        sourceApp: doc.documentType,
        x: docX,
        y: docY,
        importance: 1, // Docs are big
      });

      const memCount = doc.memories.length;
      for (let i = 0; i < memCount; i++) {
        const mem = doc.memories[i];
        const memAngle = (i / memCount) * 2 * Math.PI + hashToUnit(mem.id) * 0.5;
        const memRadius = 150 + hashToUnit(`${mem.id}-r`) * 120;

        let isExpiring = false;
        if (mem.forgetAfter) {
          isExpiring = new Date(mem.forgetAfter).getTime() - Date.now() < SEVEN_DAYS_MS;
        }

        nodes.push({
          id: mem.id,
          isDoc: false,
          label: (mem.memory || '').substring(0, 50),
          x: docX + Math.cos(memAngle) * memRadius,
          y: docY + Math.sin(memAngle) * memRadius,
          importance: 0.5,
          isExpiring,
        });

        // Structural edge (Document -> Memory)
        links.push({
          id: `dm-${doc.id}-${mem.id}`,
          source: doc.id,
          target: mem.id,
          type: 'derives',
          weight: 0.3,
        });

        // Memory relations
        const relations = mem.memoryRelations || {};
        const fallback = mem.parentMemoryId ? { [mem.parentMemoryId]: 'updates' } : {};
        const mergedRelations = Object.keys(relations).length > 0 ? relations : fallback;

        for (const [targetId, relType] of Object.entries(mergedRelations)) {
          links.push({
            id: `rel-${targetId}-${mem.id}`,
            source: targetId,
            target: mem.id,
            type: relType || 'updates',
            weight: 0.8,
          });
        }
      }
    }

    return { nodes, edges: links };
  }, [data, filter]);

  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    if (nodes.length === 0) {
      simRef.current?.stop();
      simRef.current = null;
      return;
    }

    // Filter valid edges (targets/sources must exist)
    const validNodeIds = new Set(nodes.map(n => n.id));
    const validLinks = edges.filter(e =>
      validNodeIds.has(typeof e.source === 'string' ? e.source : e.source.id) &&
      validNodeIds.has(typeof e.target === 'string' ? e.target : e.target.id)
    );

    const w = svgRef.current.clientWidth || 800;
    const h = svgRef.current.clientHeight || 600;

    const sim = d3.forceSimulation<Node>(nodes)
      .alphaDecay(0.06)
      .force('link', d3.forceLink<Node, Link>(validLinks).id(d => d.id).distance(d => d.type === 'derives' ? 120 : 60).strength(0.2))
      .force('charge', d3.forceManyBody().strength(d => (d as Node).isDoc ? -300 : -100))
      .force('center', d3.forceCenter(w / 2, h / 2))
      .force('collision', d3.forceCollide<Node>().radius(d => d.isDoc ? 30 : 18));
    simRef.current = sim;

    const g = svg.append('g');

    svg.call(
      d3.zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.1, 4])
        .on('zoom', ev => g.attr('transform', ev.transform)),
    );

    const edgeLines = g.append('g').selectAll('line')
      .data(validLinks)
      .join('line')
      .attr('stroke', d => d.type === 'derives' ? '#00D4FF40' : '#00D4FFAA')
      .attr('stroke-width', d => d.type === 'derives' ? 1 : 2);

    const evidenceSet = new Set(showEvidence ? citedIds : []);

    const node = g.append('g')
      .selectAll<SVGCircleElement, Node>('circle')
      .data(nodes)
      .join('circle')
      .attr('r', d => {
        const baseRadius = d.isDoc ? 16 : 8;
        return evidenceSet.has(d.id) ? baseRadius + 4 : baseRadius;
      })
      .attr('fill', d => evidenceSet.has(d.id) ? 'var(--shail-evidence, #8a8ad4)' : (d.isDoc ? '#1c1c24' : '#FFFFFF'))
      .attr('fill-opacity', d => d.isDoc ? 1 : 0.95)
      .attr('stroke', d => {
        if (evidenceSet.has(d.id)) return 'var(--shail-evidence, #8a8ad4)';
        if (d.isDoc) return '#888888';
        if (d.isExpiring) return '#FF9900';
        return '#00D4FF';
      })
      .attr('stroke-width', d => evidenceSet.has(d.id) ? 3 : (d.isDoc ? 2 : 2))
      .style('cursor', 'pointer')
      .on('click', (_ev, d) => {
        if (!d.isDoc) setSelectedId(d.id);
      });

    node.append('title').text(d => d.label);

    node.call(
      d3.drag<SVGCircleElement, Node>()
        .on('start', (_ev, d) => { d.fx = d.x; d.fy = d.y; })
        .on('drag', (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
        .on('end', () => {}),
    );

    const labels = g.append('g')
      .selectAll<SVGTextElement, Node>('text')
      .data(nodes)
      .join('text')
      .attr('font-size', d => d.isDoc ? 12 : 10)
      .attr('font-family', '-apple-system, BlinkMacSystemFont, "SF Pro Rounded", sans-serif')
      .attr('font-weight', d => d.isDoc ? '700' : '500')
      .attr('fill', d => evidenceSet.has(d.id) ? 'var(--shail-evidence, #8a8ad4)' : (d.isDoc ? '#AAAAAA' : '#FFFFFF'))
      .attr('fill-opacity', 0.85)
      .attr('text-anchor', 'middle')
      .attr('dy', d => d.isDoc ? -22 : -14)
      .style('pointer-events', 'none')
      .style('text-shadow', '0 1px 4px rgba(0,0,0,0.9), 0 0 8px rgba(0,0,0,0.6)')
      .text(d => d.label.slice(0, 22));

    sim.on('tick', () => {
      edgeLines
        .attr('x1', d => (d.source as Node).x!)
        .attr('y1', d => (d.source as Node).y!)
        .attr('x2', d => (d.target as Node).x!)
        .attr('y2', d => (d.target as Node).y!);
      node.attr('cx', d => d.x!).attr('cy', d => d.y!);
      labels.attr('x', d => d.x!).attr('y', d => d.y!);
    });

    return () => { sim.stop(); };
  }, [nodes, edges, showEvidence, citedIds]);

  const hasEvidence = flag('ui_v2') && citedIds.length > 0;
  const selectedRecord = selectedMemory.data as any; // Type as any since MemoryRecord changed somewhat

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: '32px 48px 20px', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexShrink: 0, gap: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 600, color: 'var(--shail-text-primary)', letterSpacing: '-0.5px' }}>
            Knowledge Graph
          </h1>
          <p style={{ margin: '5px 0 0', fontSize: 13, color: 'var(--shail-text-muted)', lineHeight: 1.5 }}>
            {data?.documents?.length || 0} documents · {nodes.filter(n => !n.isDoc).length} memories
            {filter !== 'all' && ` · filtered to ${SOURCE_LABEL[filter] ?? filter}`}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {hasEvidence && (
            <button
              onClick={() => setShowEvidence(s => !s)}
              style={{
                padding: '5px 11px', borderRadius: 20, fontSize: 11, fontWeight: 500, cursor: 'pointer',
                border: `1px solid ${showEvidence ? 'var(--shail-evidence)50' : 'var(--shail-border-subtle)'}`,
                background: showEvidence ? 'var(--shail-evidence-soft)' : 'transparent',
                color: showEvidence ? 'var(--shail-evidence)' : 'var(--shail-text-muted)',
                transition: 'all 0.12s',
              }}
            >
              ◈ Evidence
            </button>
          )}
          {(['all', ...SOURCES] as const).map(s => {
            const isActive = filter === s;
            const color = s === 'all' ? 'var(--shail-text-muted)' : (SOURCE_COLOR[s] ?? 'var(--shail-text-muted)');
            const activeBg = s === 'all' ? 'var(--shail-bg-raised)' : (SOURCE_COLOR[s] ?? '#888') + '18';
            const activeBorder = s === 'all' ? 'var(--shail-border-strong)' : (SOURCE_COLOR[s] ?? '#888') + '50';
            return (
              <button key={s} onClick={() => setFilter(s)} style={{
                padding: '5px 11px', borderRadius: 20, fontSize: 11, fontWeight: 500, cursor: 'pointer',
                border: `1px solid ${isActive ? activeBorder : 'var(--shail-border-subtle)'}`,
                background: isActive ? activeBg : 'transparent',
                color: isActive ? color : 'var(--shail-text-muted)',
                transition: 'all 0.12s',
              }}>
                {s === 'all' ? 'All' : SOURCE_LABEL[s]}
              </button>
            );
          })}
        </div>
      </div>

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        <div style={{ flex: 1, position: 'relative', background: '#0D0D14' }}>
          <svg ref={svgRef} style={{ width: '100%', height: '100%' }} />
          {isLoading && (
            <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'var(--shail-text-muted)', fontSize: 13 }}>
              Loading graph…
            </div>
          )}
          {!isLoading && !!error && (
            <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'var(--shail-warning)', fontSize: 13, padding: 24, textAlign: 'center' }}>
              Failed to load the knowledge graph.
            </div>
          )}
          {!isLoading && !error && nodes.length === 0 && (
            <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'var(--shail-text-muted)', fontSize: 13 }}>
              No graph nodes match this filter.
            </div>
          )}
        </div>
        {selectedId && !selectedId.startsWith('doc_') && (
          <div style={{
            width: 320,
            background: 'var(--shail-bg-surface)',
            borderLeft: '1px solid var(--shail-border-subtle)',
            padding: 20,
            overflowY: 'auto',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--shail-text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                Memory
              </span>
              <button
                onClick={() => setSelectedId(null)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--shail-text-muted)', fontSize: 16, lineHeight: 1, opacity: 0.5 }}
                onMouseEnter={e => (e.currentTarget.style.opacity = '1')}
                onMouseLeave={e => (e.currentTarget.style.opacity = '0.5')}
              >
                ×
              </button>
            </div>
            {selectedMemory.isLoading && (
              <div style={{ fontSize: 13, color: 'var(--shail-text-muted)' }}>Loading memory…</div>
            )}
            {!selectedMemory.isLoading && selectedRecord && (
              <MemoryCard record={selectedRecord} onDeleted={() => setSelectedId(null)} />
            )}
            {!selectedMemory.isLoading && !selectedRecord && (
              <div style={{ fontSize: 13, color: 'var(--shail-text-muted)' }}>Memory details unavailable.</div>
            )}
          </div>
        )}
      </div>

      <div style={{
        padding: '8px 48px',
        display: 'flex',
        gap: 18,
        fontSize: 10,
        color: 'var(--shail-text-muted)',
        borderTop: '1px solid var(--shail-border-subtle)',
        flexShrink: 0,
        opacity: 0.8,
      }}>
        <span>◎ Document</span>
        <span>● Memory</span>
        <span style={{ color: '#FF9900' }}>● Expiring</span>
        {showEvidence && <span style={{ color: 'var(--shail-evidence)' }}>● Evidence</span>}
        <span style={{ marginLeft: 'auto' }}>Scroll to zoom · drag to pan · click memory to inspect</span>
      </div>
    </div>
  );
}
