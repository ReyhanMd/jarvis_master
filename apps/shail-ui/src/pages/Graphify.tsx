/**
 * Graphify maps approved local files into a rebuildable relationship graph.
 *
 * It stays pointer-first: the graph stores file paths, metadata, short
 * snippets, and derived relationships. File contents are read only when a user
 * asks a question that needs matching approved files.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  api,
  LocalCanonicalFact,
  LocalAnswerResponse,
  LocalEvidenceResponse,
  LocalEvidenceItem,
  LocalGraphNode,
  LocalGraphRelation,
  LocalIntelligencePacketResponse,
  LocalIntelligenceStatusResponse,
  LocalReasoningConflictsResponse,
  LocalReasoningGroup,
  LocalReasoningSearchResponse,
  LocalReasoningStatusResponse,
  LocalSemanticEntity,
  LocalSemanticFact,
  LocalSemanticsJobResponse,
  LocalSemanticTask,
  LocalSemanticsSearchResponse,
  LocalSemanticsStatusResponse,
  PathTreeNode,
} from '../api';
import { EmptyState } from '../components/primitives';

const MONO = 'ui-monospace,"SF Mono",Menlo,monospace';
const INITIAL_GRAPH_LIMIT = 250;
const BUILD_GRAPH_LIMIT = 1000;

const KIND_COLOR: Record<string, string> = {
  code: '#7aa6e0',
  doc: '#fbbf24',
  data: '#22c55e',
  media: '#c084fc',
  log: '#9ca3af',
  other: '#666',
};

const NODE_COLOR: Record<string, string> = {
  local_file: '#7aa6e0',
  folder: '#9ca3af',
  project: '#22c55e',
  topic: '#fbbf24',
  entity: '#c084fc',
  file_version_group: '#fb7185',
  content_hash: '#94a3b8',
  browser_memory: '#38bdf8',
  person: '#38bdf8',
  organization: '#22c55e',
  date: '#fbbf24',
  task: '#fb7185',
  decision: '#c084fc',
  metric: '#60a5fa',
  fact: '#94a3b8',
  money_value: '#22c55e',
  percent_value: '#fbbf24',
  document_section: '#9ca3af',
  fact_group: '#f97316',
};

interface Stats {
  total: number;
  total_files: number;
  total_dirs: number;
  by_kind: Record<string, number>;
  embedded: number;
  last_indexed_at: number | null;
}

type ViewMode = 'tree' | 'graph' | 'evidence' | 'objects' | 'reasoning' | 'intelligence';

export function Graphify() {
  const [view, setView] = useState<ViewMode>('graph');
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [childrenByPath, setChildrenByPath] = useState<Record<string, PathTreeNode[]>>({});
  const [rootNodes, setRootNodes] = useState<PathTreeNode[]>([]);
  const [selectedFile, setSelectedFile] = useState<PathTreeNode | null>(null);
  const [selectedGraphNode, setSelectedGraphNode] = useState<LocalGraphNode | null>(null);
  const [graphNodes, setGraphNodes] = useState<LocalGraphNode[]>([]);
  const [graphRelations, setGraphRelations] = useState<LocalGraphRelation[]>([]);
  const [graphQuery, setGraphQuery] = useState('');
  const [evidenceQuery, setEvidenceQuery] = useState('');
  const [evidence, setEvidence] = useState<LocalEvidenceResponse | null>(null);
  const [answerPreview, setAnswerPreview] = useState<LocalAnswerResponse | null>(null);
  const [intelligenceQuery, setIntelligenceQuery] = useState('');
  const [intelligencePacket, setIntelligencePacket] = useState<LocalIntelligencePacketResponse | null>(null);
  const [intelligenceStatus, setIntelligenceStatus] = useState<LocalIntelligenceStatusResponse | null>(null);
  const [intelligenceK, setIntelligenceK] = useState(12);
  const [intelligenceIncludeAnswer, setIntelligenceIncludeAnswer] = useState(true);
  const [intelligenceIncludeGraph, setIntelligenceIncludeGraph] = useState(true);
  const [semanticQuery, setSemanticQuery] = useState('');
  const [semanticStatus, setSemanticStatus] = useState<LocalSemanticsStatusResponse | null>(null);
  const [semantics, setSemantics] = useState<LocalSemanticsSearchResponse | null>(null);
  const [semanticMode, setSemanticMode] = useState<'deterministic' | 'hybrid'>('deterministic');
  const [semanticLimit, setSemanticLimit] = useState(500);
  const [semanticForce, setSemanticForce] = useState(false);
  const [semanticJob, setSemanticJob] = useState<LocalSemanticsJobResponse | null>(null);
  const [reasoningQuery, setReasoningQuery] = useState('');
  const [reasoningLimit, setReasoningLimit] = useState(5000);
  const [reasoningForce, setReasoningForce] = useState(false);
  const [reasoningStatus, setReasoningStatus] = useState<LocalReasoningStatusResponse | null>(null);
  const [reasoning, setReasoning] = useState<LocalReasoningSearchResponse | null>(null);
  const [reasoningConflicts, setReasoningConflicts] = useState<LocalReasoningConflictsResponse | null>(null);
  const [buildingReasoning, setBuildingReasoning] = useState(false);
  const [refreshingPath, setRefreshingPath] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [buildingGraph, setBuildingGraph] = useState(false);
  const [buildingEvidence, setBuildingEvidence] = useState(false);
  const [buildingAnswer, setBuildingAnswer] = useState(false);
  const [buildingIntelligence, setBuildingIntelligence] = useState(false);
  const [buildingSemantics, setBuildingSemantics] = useState(false);
  const [lastIndexedTs, setLastIndexedTs] = useState<number | null>(null);

  const graphNodeById = useMemo(() => {
    const out = new Map<string, LocalGraphNode>();
    graphNodes.forEach(node => out.set(node.id, node));
    return out;
  }, [graphNodes]);

  const selectedRelations = useMemo(() => {
    if (!selectedGraphNode) return [];
    return graphRelations.filter(
      rel => rel.source_id === selectedGraphNode.id || rel.target_id === selectedGraphNode.id,
    );
  }, [graphRelations, selectedGraphNode]);

  const graphCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    graphNodes.forEach(node => {
      counts[node.type] = (counts[node.type] || 0) + 1;
    });
    return counts;
  }, [graphNodes]);

  const loadStats = useCallback(async () => {
    try {
      const s = await api.pathIndexStats();
      setStats(s);
      return s;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, []);

  const loadRoots = useCallback(async () => {
    try {
      const r = await api.pathIndexTree(undefined, 1, 500);
      setRootNodes(r.nodes.filter(n => n.is_dir));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  const loadGraph = useCallback(async () => {
    try {
      const g = await api.localGraph(INITIAL_GRAPH_LIMIT);
      setGraphNodes(g.nodes || []);
      setGraphRelations(g.relations || []);
      setError(null);
    } catch (e) {
      setError(readableGraphError(e));
    }
  }, []);

  const loadSemantics = useCallback(async () => {
    try {
      const [status, search] = await Promise.all([
        api.localSemanticsStatus(),
        api.localSemanticsSearch('', 50),
      ]);
      setSemanticStatus(status);
      setSemantics(search);
    } catch (e) {
      setError(readableGraphError(e));
    }
  }, []);

  const loadReasoning = useCallback(async () => {
    try {
      const [status, search, conflicts] = await Promise.all([
        api.localReasoningStatus(),
        api.localReasoningSearch('', 50),
        api.localReasoningConflicts(50),
      ]);
      setReasoningStatus(status);
      setReasoning(search);
      setReasoningConflicts(conflicts);
    } catch (e) {
      setError(readableGraphError(e));
    }
  }, []);

  const loadIntelligenceStatus = useCallback(async () => {
    try {
      const status = await api.localIntelligenceStatus();
      setIntelligenceStatus(status);
    } catch (e) {
      setError(readableGraphError(e));
    }
  }, []);

  useEffect(() => {
    (async () => {
      const s = await loadStats();
      if (s) setLastIndexedTs(s.last_indexed_at);
      void loadRoots();
      void loadGraph();
      void loadSemantics();
      void loadReasoning();
      void loadIntelligenceStatus();
    })();
  }, [loadStats, loadRoots, loadGraph, loadSemantics, loadReasoning, loadIntelligenceStatus]);

  useEffect(() => {
    const t = setInterval(async () => {
      const s = await loadStats();
      if (!s) return;
      if (s.last_indexed_at && s.last_indexed_at !== lastIndexedTs) {
        setLastIndexedTs(s.last_indexed_at);
        await Promise.allSettled([
          loadRoots(),
          loadGraph(),
          loadSemantics(),
          loadReasoning(),
          ...Array.from(expanded).map(path => loadChildren(path)),
        ]);
      }
    }, 5000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastIndexedTs, expanded, loadGraph, loadRoots, loadStats, loadSemantics, loadReasoning]);

  useEffect(() => {
    const active = semanticJob && ['pending', 'running'].includes(semanticJob.status);
    if (!active) return;
    const t = setInterval(async () => {
      try {
        const job = await api.localSemanticsJob(semanticJob.job_id);
        setSemanticJob(job);
        await loadSemantics();
        if (!['pending', 'running'].includes(job.status)) {
          await loadGraph();
        }
      } catch (e) {
        setError(readableGraphError(e));
      }
    }, 2000);
    return () => clearInterval(t);
  }, [semanticJob, loadSemantics, loadGraph]);

  async function loadChildren(path: string) {
    try {
      const r = await api.pathIndexTree(path, 1, 500);
      const children = r.nodes.filter(n => n.id !== path);
      setChildrenByPath(prev => ({ ...prev, [path]: children }));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function toggle(node: PathTreeNode) {
    if (!node.is_dir) {
      setSelectedFile(node);
      return;
    }
    const next = new Set(expanded);
    if (next.has(node.id)) {
      next.delete(node.id);
    } else {
      next.add(node.id);
      if (!childrenByPath[node.id]) await loadChildren(node.id);
    }
    setExpanded(next);
  }

  async function handleRefreshPath(path: string) {
    setRefreshingPath(path);
    try {
      await api.pathIndexEmbed(path);
      const parent = path.split('/').slice(0, -1).join('/');
      if (parent) await loadChildren(parent);
      await loadGraph();
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRefreshingPath(null);
    }
  }

  async function handleOpenPath(path: string) {
    try {
      await api.pathIndexOpen(path);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleSync() {
    setSyncing(true);
    try {
      await api.pathIndexSync();
      const t0 = Date.now();
      while (Date.now() - t0 < 30000) {
        await new Promise(r => setTimeout(r, 2000));
        const s = await loadStats();
        if (s && s.last_indexed_at && s.last_indexed_at !== lastIndexedTs) {
          setLastIndexedTs(s.last_indexed_at);
          await loadRoots();
          await handleBuildGraph();
          break;
        }
      }
    } finally {
      setSyncing(false);
    }
  }

  async function handleBuildGraph() {
    setBuildingGraph(true);
    try {
      await api.localGraphBuild(BUILD_GRAPH_LIMIT);
      await loadGraph();
      setError(null);
    } catch (e) {
      setError(readableGraphError(e));
    } finally {
      setBuildingGraph(false);
    }
  }

  async function handleBuildSemantics() {
    setBuildingSemantics(true);
    try {
      if (semanticMode === 'deterministic') {
        await api.localSemanticsBuild(semanticLimit, semanticForce, 'deterministic');
        await loadSemantics();
        await handleBuildGraph();
      } else {
        const job = await api.localSemanticsJobCreate({
          mode: 'hybrid',
          limit: semanticLimit,
          force: semanticForce,
        });
        setSemanticJob(job);
        await loadSemantics();
      }
      setError(null);
    } catch (e) {
      setError(readableGraphError(e));
    } finally {
      setBuildingSemantics(false);
    }
  }

  async function handleCancelSemanticsJob() {
    if (!semanticJob) return;
    try {
      const job = await api.cancelLocalSemanticsJob(semanticJob.job_id);
      setSemanticJob(job);
      await loadSemantics();
    } catch (e) {
      setError(readableGraphError(e));
    }
  }

  async function handleSemanticSearch() {
    try {
      const result = await api.localSemanticsSearch(semanticQuery.trim(), 80);
      setSemantics(result);
      setError(null);
    } catch (e) {
      setError(readableGraphError(e));
    }
  }

  async function handleBuildReasoning() {
    setBuildingReasoning(true);
    try {
      await api.localReasoningBuild({ limit: reasoningLimit, force: reasoningForce });
      await loadReasoning();
      await loadGraph();
      setError(null);
    } catch (e) {
      setError(readableGraphError(e));
    } finally {
      setBuildingReasoning(false);
    }
  }

  async function handleReasoningSearch() {
    try {
      const result = await api.localReasoningSearch(reasoningQuery.trim(), 80);
      setReasoning(result);
      const conflicts = await api.localReasoningConflicts(80);
      setReasoningConflicts(conflicts);
      setError(null);
    } catch (e) {
      setError(readableGraphError(e));
    }
  }

  async function handleGraphSearch() {
    try {
      const q = graphQuery.trim();
      const g = q ? await api.localGraphSearch(q, 40) : await api.localGraph(INITIAL_GRAPH_LIMIT);
      setGraphNodes(g.nodes || []);
      setGraphRelations(g.relations || []);
      setSelectedGraphNode(null);
      setError(null);
    } catch (e) {
      setError(readableGraphError(e));
    }
  }

  async function handleSelectGraphNode(node: LocalGraphNode) {
    setSelectedGraphNode(node);
    try {
      const g = await api.localGraphNeighbors(node.id, 80);
      const nodeIds = new Set(graphNodes.map(n => n.id));
      const nextNodes = [...graphNodes];
      for (const n of g.nodes || []) {
        if (!nodeIds.has(n.id)) {
          nodeIds.add(n.id);
          nextNodes.push(n);
        }
      }
      const relKeys = new Set(graphRelations.map(r => `${r.source_id}|${r.target_id}|${r.relation}`));
      const nextRelations = [...graphRelations];
      for (const r of g.relations || []) {
        const key = `${r.source_id}|${r.target_id}|${r.relation}`;
        if (!relKeys.has(key)) {
          relKeys.add(key);
          nextRelations.push(r);
        }
      }
      setGraphNodes(nextNodes);
      setGraphRelations(nextRelations);
    } catch (e) {
      setError(readableGraphError(e));
    }
  }

  async function handleBuildEvidence() {
    const q = evidenceQuery.trim();
    if (!q) {
      setError('Enter a question to preview evidence.');
      return;
    }
    setBuildingEvidence(true);
    try {
      const bundle = await api.localEvidence(q, 8, true);
      setEvidence(bundle);
      setAnswerPreview(null);
      setError(null);
    } catch (e) {
      setError(readableGraphError(e));
    } finally {
      setBuildingEvidence(false);
    }
  }

  async function handleBuildAnswer() {
    const q = evidenceQuery.trim();
    if (!q) {
      setError('Enter a question to preview an answer.');
      return;
    }
    setBuildingAnswer(true);
    try {
      const answer = await api.localAnswer(q, 8, true);
      setAnswerPreview(answer);
      setError(null);
    } catch (e) {
      setError(readableGraphError(e));
    } finally {
      setBuildingAnswer(false);
    }
  }

  async function handleBuildIntelligence() {
    const q = intelligenceQuery.trim();
    if (!q) {
      setError('Enter a question or topic to build an intelligence packet.');
      return;
    }
    setBuildingIntelligence(true);
    try {
      const packet = await api.localIntelligencePacket({
        query: q,
        k: intelligenceK,
        include_graph: intelligenceIncludeGraph,
        include_semantics: true,
        include_reasoning: true,
        include_answer: intelligenceIncludeAnswer,
      });
      setIntelligencePacket(packet);
      await loadIntelligenceStatus();
      setError(null);
    } catch (e) {
      setError(readableGraphError(e));
    } finally {
      setBuildingIntelligence(false);
    }
  }

  return (
    <div style={{ flex: 1, padding: '40px 48px', overflowY: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 6, gap: 16 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 500, color: '#fff' }}>Graphify</h1>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <Segmented value={view} onChange={setView} />
          <button onClick={handleBuildGraph} disabled={buildingGraph} style={buttonStyle('secondary', buildingGraph)}>
            {buildingGraph ? 'Building graph...' : 'Build graph'}
          </button>
          <button onClick={handleSync} disabled={syncing} style={buttonStyle('secondary', syncing)}>
            {syncing ? 'Scanning...' : 'Re-scan approved folders'}
          </button>
        </div>
      </div>
      <p style={{ margin: '0 0 24px', fontSize: 13, color: '#777', maxWidth: 900, lineHeight: 1.5 }}>
        Graphify maps only folders approved during local-file setup. SHAIL keeps local pointers,
        metadata, short snippets, and derived relationships like project, topic, duplicate, version,
        and nearby-file links. Blocked folders stay out of the graph.
      </p>

      {error && (
        <div style={{ marginBottom: 18, padding: '10px 14px', background: '#1a0808',
          border: '1px solid #3a1010', borderRadius: 7, color: '#ef9a9a', fontSize: 12 }}>
          {error}
        </div>
      )}

      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', marginBottom: 24 }}>
        <Stat label="FILES" value={stats?.total_files ?? '-'} />
        <Stat label="FOLDERS" value={stats?.total_dirs ?? '-'} />
        <Stat label="GRAPH NODES" value={graphNodes.length} color="#7aa6e0" />
        <Stat label="RELATIONS" value={graphRelations.length} color="#22c55e" />
        <Stat label="OBJECTS" value={(semanticStatus?.facts ?? 0) + (semanticStatus?.tasks ?? 0) + entityTotal(semanticStatus)} color="#c084fc" />
        <Stat label="RESOLVED" value={reasoningStatus?.resolved ?? 0} color="#f97316" />
        <Stat label="CONFLICTS" value={reasoningStatus?.conflicts ?? 0} color="#fb7185" />
        <Stat label="PACKETS" value={intelligenceStatus?.packets ?? 0} color="#38bdf8" />
        {Object.entries(graphCounts).slice(0, 4).map(([k, n]) => (
          <Stat key={k} label={k.replaceAll('_', ' ').toUpperCase()} value={n} color={NODE_COLOR[k] || '#666'} />
        ))}
      </div>

      {view === 'tree' ? (
        <TreeSurface
          rootNodes={rootNodes}
          expanded={expanded}
          childrenByPath={childrenByPath}
          selected={selectedFile}
          refreshingPath={refreshingPath}
          onToggle={toggle}
          onRefreshPath={handleRefreshPath}
          onOpenPath={handleOpenPath}
        />
      ) : view === 'evidence' ? (
        <EvidenceSurface
          query={evidenceQuery}
          evidence={evidence}
          answer={answerPreview}
          loading={buildingEvidence}
          answerLoading={buildingAnswer}
          onQueryChange={setEvidenceQuery}
          onBuild={handleBuildEvidence}
          onAnswer={handleBuildAnswer}
        />
      ) : view === 'objects' ? (
        <ObjectsSurface
          query={semanticQuery}
          status={semanticStatus}
          semantics={semantics}
          loading={buildingSemantics}
          mode={semanticMode}
          limit={semanticLimit}
          force={semanticForce}
          job={semanticJob || semanticStatus?.queue?.active_job || null}
          queue={semanticStatus?.queue}
          onQueryChange={setSemanticQuery}
          onModeChange={setSemanticMode}
          onLimitChange={setSemanticLimit}
          onForceChange={setSemanticForce}
          onSearch={handleSemanticSearch}
          onBuild={handleBuildSemantics}
          onCancel={handleCancelSemanticsJob}
        />
      ) : view === 'reasoning' ? (
        <ReasoningSurface
          query={reasoningQuery}
          status={reasoningStatus}
          reasoning={reasoning}
          conflicts={reasoningConflicts}
          loading={buildingReasoning}
          limit={reasoningLimit}
          force={reasoningForce}
          onQueryChange={setReasoningQuery}
          onLimitChange={setReasoningLimit}
          onForceChange={setReasoningForce}
          onSearch={handleReasoningSearch}
          onBuild={handleBuildReasoning}
        />
      ) : view === 'intelligence' ? (
        <IntelligenceSurface
          query={intelligenceQuery}
          packet={intelligencePacket}
          status={intelligenceStatus}
          loading={buildingIntelligence}
          k={intelligenceK}
          includeAnswer={intelligenceIncludeAnswer}
          includeGraph={intelligenceIncludeGraph}
          onQueryChange={setIntelligenceQuery}
          onKChange={setIntelligenceK}
          onIncludeAnswerChange={setIntelligenceIncludeAnswer}
          onIncludeGraphChange={setIntelligenceIncludeGraph}
          onBuild={handleBuildIntelligence}
        />
      ) : (
        <GraphSurface
          nodes={graphNodes}
          relations={graphRelations}
          nodeById={graphNodeById}
          selected={selectedGraphNode}
          selectedRelations={selectedRelations}
          query={graphQuery}
          onQueryChange={setGraphQuery}
          onSearch={handleGraphSearch}
          onSelect={handleSelectGraphNode}
        />
      )}
    </div>
  );
}

function TreeSurface({
  rootNodes, expanded, childrenByPath, selected, refreshingPath, onToggle, onRefreshPath, onOpenPath,
}: {
  rootNodes: PathTreeNode[];
  expanded: Set<string>;
  childrenByPath: Record<string, PathTreeNode[]>;
  selected: PathTreeNode | null;
  refreshingPath: string | null;
  onToggle: (n: PathTreeNode) => void;
  onRefreshPath: (path: string) => void;
  onOpenPath: (path: string) => void;
}) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 18, alignItems: 'start' }}>
      <Panel>
        {rootNodes.length === 0 ? (
          <EmptyState
            title="No approved folders indexed"
            hint="Complete local-file onboarding, approve one folder, then scan it."
          />
        ) : (
          rootNodes.map(root => (
            <TreeRow
              key={root.id}
              node={root}
              depth={0}
              expanded={expanded}
              childrenByPath={childrenByPath}
              onToggle={onToggle}
              selected={selected?.id ?? null}
            />
          ))
        )}
      </Panel>
      <Panel sticky>
        {!selected ? (
          <div style={{ fontSize: 12, color: '#777' }}>Pick a file from the tree to inspect.</div>
        ) : (
          <FileDetail
            node={selected}
            refreshing={refreshingPath === selected.id}
            onRefresh={() => onRefreshPath(selected.id)}
            onOpen={() => onOpenPath(selected.id)}
          />
        )}
      </Panel>
    </div>
  );
}

function GraphSurface({
  nodes, relations, nodeById, selected, selectedRelations, query, onQueryChange, onSearch, onSelect,
}: {
  nodes: LocalGraphNode[];
  relations: LocalGraphRelation[];
  nodeById: Map<string, LocalGraphNode>;
  selected: LocalGraphNode | null;
  selectedRelations: LocalGraphRelation[];
  query: string;
  onQueryChange: (value: string) => void;
  onSearch: () => void;
  onSelect: (node: LocalGraphNode) => void;
}) {
  const visibleNodes = nodes
    .filter(n => n.type !== 'browser_memory')
    .slice()
    .sort((a, b) => `${a.type}:${nodeTitle(a)}`.localeCompare(`${b.type}:${nodeTitle(b)}`))
    .slice(0, 180);

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 360px', gap: 18, alignItems: 'start' }}>
      <Panel>
        <div style={{ display: 'flex', gap: 8, padding: '0 12px 12px' }}>
          <input
            value={query}
            onChange={e => onQueryChange(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') onSearch(); }}
            placeholder="Search files, topics, projects, or entities"
            style={{
              flex: 1, minWidth: 0, background: '#050505', border: '1px solid #1b1b1b',
              color: '#ddd', borderRadius: 6, padding: '8px 10px', fontSize: 12,
            }}
          />
          <button onClick={onSearch} style={buttonStyle('primary', false)}>Search</button>
        </div>
        {visibleNodes.length === 0 ? (
          <EmptyState
            title="No graph built yet"
            hint="Build the graph after indexing at least one approved folder."
          />
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 8, padding: '0 12px 12px' }}>
            {visibleNodes.map(node => (
              <GraphNodeButton
                key={node.id}
                node={node}
                relationCount={relations.filter(r => r.source_id === node.id || r.target_id === node.id).length}
                selected={selected?.id === node.id}
                onClick={() => onSelect(node)}
              />
            ))}
          </div>
        )}
      </Panel>
      <Panel sticky>
        {!selected ? (
          <div style={{ fontSize: 12, color: '#777' }}>Pick a graph node to inspect its relationships.</div>
        ) : (
          <GraphDetail node={selected} relations={selectedRelations} nodeById={nodeById} />
        )}
      </Panel>
    </div>
  );
}

function EvidenceSurface({
  query, evidence, answer, loading, answerLoading, onQueryChange, onBuild, onAnswer,
}: {
  query: string;
  evidence: LocalEvidenceResponse | null;
  answer: LocalAnswerResponse | null;
  loading: boolean;
  answerLoading: boolean;
  onQueryChange: (value: string) => void;
  onBuild: () => void;
  onAnswer: () => void;
}) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 360px', gap: 18, alignItems: 'start' }}>
      <Panel>
        <div style={{ display: 'flex', gap: 8, padding: '0 12px 12px' }}>
          <input
            value={query}
            onChange={e => onQueryChange(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') onBuild(); }}
            placeholder="Ask a local-file question to preview evidence"
            style={{
              flex: 1, minWidth: 0, background: '#050505', border: '1px solid #1b1b1b',
              color: '#ddd', borderRadius: 6, padding: '8px 10px', fontSize: 12,
            }}
          />
          <button onClick={onBuild} disabled={loading} style={buttonStyle('primary', loading)}>
            {loading ? 'Building...' : 'Build evidence'}
          </button>
          <button onClick={onAnswer} disabled={answerLoading} style={buttonStyle('secondary', answerLoading)}>
            {answerLoading ? 'Answering...' : 'Build answer'}
          </button>
        </div>
        {answer && (
          <div style={{
            margin: '0 12px 12px', padding: 14, border: '1px solid #202020',
            borderRadius: 7, background: '#090909',
          }}>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
              <Badge label={`answer: ${answer.confidence}`} color={confidenceColor(answer.confidence)} />
              <Badge label={`score: ${Math.round((answer.quality_score || 0) * 100)}%`} color="#7aa6e0" />
              <Badge label={`citations: ${answer.citations.length}`} color="#22c55e" />
            </div>
            <div style={{ fontSize: 13, color: '#e6e6e6', lineHeight: 1.55 }}>{answer.answer}</div>
            {answer.warnings.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <SectionLabel text="WARNINGS" />
                {answer.warnings.slice(0, 5).map(w => (
                  <div key={w} style={{ fontSize: 12, color: '#fca5a5', marginTop: 5 }}>{w}</div>
                ))}
              </div>
            )}
            {answer.follow_up_questions.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <SectionLabel text="FOLLOW UP" />
                {answer.follow_up_questions.slice(0, 3).map(q => (
                  <div key={q} style={{ fontSize: 12, color: '#aaa', marginTop: 5 }}>{q}</div>
                ))}
              </div>
            )}
          </div>
        )}
        {!evidence ? (
          <EmptyState
            title="No evidence preview yet"
            hint="Ask a question to see which approved files SHAIL would use and why."
          />
        ) : evidence.selected_files.length === 0 ? (
          <EmptyState
            title="No selected evidence"
            hint="SHAIL did not find strong approved local-file evidence for this question."
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '0 12px 12px' }}>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 2 }}>
              <Badge label={`confidence: ${evidence.confidence}`} color={confidenceColor(evidence.confidence)} />
              <Badge label={`selected: ${evidence.selected_files.length}`} color="#7aa6e0" />
              <Badge label={`related: ${evidence.graph_expansions.length}`} color="#22c55e" />
              <Badge label={`suppressed: ${evidence.suppressed_files.length}`} color="#fb7185" />
            </div>
            {evidence.selected_files.map(item => (
              <EvidenceCard key={item.id} item={item} />
            ))}
          </div>
        )}
      </Panel>
      <Panel sticky>
        {!evidence && !answer ? (
          <div style={{ fontSize: 12, color: '#777', padding: '0 18px' }}>
            Evidence Preview shows the answer packet before the LLM sees it.
          </div>
        ) : answer ? (
          <AnswerInspector answer={answer} evidence={evidence} />
        ) : (
          <EvidenceInspector evidence={evidence} />
        )}
      </Panel>
    </div>
  );
}

function ObjectsSurface({
  query, status, semantics, loading, mode, limit, force, job, queue,
  onQueryChange, onModeChange, onLimitChange, onForceChange, onSearch, onBuild, onCancel,
}: {
  query: string;
  status: LocalSemanticsStatusResponse | null;
  semantics: LocalSemanticsSearchResponse | null;
  loading: boolean;
  mode: 'deterministic' | 'hybrid';
  limit: number;
  force: boolean;
  job: LocalSemanticsJobResponse | null;
  queue?: LocalSemanticsStatusResponse['queue'];
  onQueryChange: (value: string) => void;
  onModeChange: (value: 'deterministic' | 'hybrid') => void;
  onLimitChange: (value: number) => void;
  onForceChange: (value: boolean) => void;
  onSearch: () => void;
  onBuild: () => void;
  onCancel: () => void;
}) {
  const entities = semantics?.entities ?? [];
  const facts = semantics?.facts ?? [];
  const tasks = semantics?.tasks ?? [];
  const activeJob = job && ['pending', 'running'].includes(job.status);
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 360px', gap: 18, alignItems: 'start' }}>
      <Panel>
        <div style={{ display: 'flex', gap: 8, padding: '0 12px 12px', flexWrap: 'wrap' }}>
          <input
            value={query}
            onChange={e => onQueryChange(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') onSearch(); }}
            placeholder="Search people, companies, dates, tasks, metrics, or facts"
            style={{
              flex: 1, minWidth: 0, background: '#050505', border: '1px solid #1b1b1b',
              color: '#ddd', borderRadius: 6, padding: '8px 10px', fontSize: 12,
            }}
          />
          <button onClick={onSearch} style={buttonStyle('primary', false)}>Search</button>
        </div>
        <div style={{ display: 'flex', gap: 8, padding: '0 12px 12px', flexWrap: 'wrap', alignItems: 'center' }}>
          <select
            value={mode}
            onChange={e => onModeChange(e.target.value as 'deterministic' | 'hybrid')}
            style={selectStyle}
            title="Extraction mode"
          >
            <option value="deterministic">Deterministic</option>
            <option value="hybrid">Hybrid with Ollama</option>
          </select>
          <input
            type="number"
            min={1}
            max={5000}
            value={limit}
            onChange={e => onLimitChange(Math.max(1, Math.min(5000, Number(e.target.value) || 1)))}
            style={{ ...selectStyle, width: 88 }}
            title="File limit"
          />
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#aaa', fontSize: 12 }}>
            <input type="checkbox" checked={force} onChange={e => onForceChange(e.target.checked)} />
            Force
          </label>
          <button onClick={onBuild} disabled={loading || !!activeJob} style={buttonStyle('secondary', loading || !!activeJob)}>
            {loading ? 'Extracting...' : activeJob ? 'Job running...' : 'Start extraction'}
          </button>
          {activeJob && (
            <button onClick={onCancel} style={buttonStyle('secondary', false)}>Cancel</button>
          )}
        </div>
        <div style={{ padding: '0 12px 12px', display: 'grid', gap: 8 }}>
          <div style={{ fontSize: 12, color: '#777', lineHeight: 1.45 }}>
            Deterministic extraction is fast and rule-based. Ollama enrichment reads approved files locally and extracts richer structured objects. No full file content is stored in vector memory.
          </div>
          {job && (
            <div style={{ border: '1px solid #1b1b1b', borderRadius: 7, padding: 10, background: '#070707' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 8 }}>
                <span style={{ color: '#ddd', fontSize: 12 }}>Semantic job: {job.status}</span>
                <span style={{ color: '#777', fontFamily: MONO, fontSize: 11 }}>{job.model || job.mode}</span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8 }}>
                <MiniStat label="FILES" value={`${job.files_processed}/${job.files_seen || 0}`} />
                <MiniStat label="CHUNKS" value={job.chunks_processed} />
                <MiniStat label="OBJECTS" value={job.entities + job.facts + job.tasks} />
                <MiniStat label="FAILED" value={job.files_failed} />
              </div>
              {job.warnings?.length ? (
                <div style={{ color: '#fbbf24', fontSize: 11, marginTop: 8 }}>{job.warnings.slice(0, 2).join(' ')}</div>
              ) : null}
            </div>
          )}
        </div>
        {!semantics || (entities.length + facts.length + tasks.length === 0) ? (
          <EmptyState
            title="No semantic objects extracted yet"
            hint="Run Rebuild semantics after indexing approved folders."
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '0 12px 12px' }}>
            <ObjectSection title="Facts and metrics" count={facts.length}>
              {facts.slice(0, 80).map(item => <FactCard key={item.id} item={item} />)}
            </ObjectSection>
            <ObjectSection title="Tasks" count={tasks.length}>
              {tasks.slice(0, 50).map(item => <TaskCard key={item.id} item={item} />)}
            </ObjectSection>
            <ObjectSection title="People and organizations" count={entities.length}>
              {entities.slice(0, 80).map(item => <EntityCard key={item.id} item={item} />)}
            </ObjectSection>
          </div>
        )}
      </Panel>
      <Panel sticky>
        <div style={{ padding: '0 18px' }}>
          <DetailRow k="EXTRACTOR" v={status?.extractor_version || '-'} />
          <DetailRow k="LLM" v={queue?.llm_enabled ? 'enabled' : 'opt-in off'} />
          <DetailRow k="MODEL" v={queue?.active_model || '-'} />
          <DetailRow k="QUEUE" v={`p:${queue?.pending ?? 0} r:${queue?.running ?? 0} f:${queue?.failed ?? 0}`} />
          <DetailRow k="FILES" v={Object.entries(status?.files || {}).map(([k, v]) => `${k}:${v}`).join(' ') || '-'} />
          <DetailRow k="FACTS" v={String(status?.facts ?? 0)} />
          <DetailRow k="TASKS" v={String(status?.tasks ?? 0)} />
          <DetailRow k="ENTITIES" v={String(entityTotal(status))} />
          <SectionLabel text="ENTITY TYPES" />
          {Object.entries(status?.entities || {}).length === 0 ? (
            <div style={{ fontSize: 12, color: '#777', marginTop: 8 }}>No entity counts yet.</div>
          ) : Object.entries(status?.entities || {}).map(([k, v]) => (
            <DetailRow key={k} k={k.toUpperCase()} v={String(v)} />
          ))}
        </div>
      </Panel>
    </div>
  );
}

function ObjectSection({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  if (count === 0) return null;
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <div style={{ fontSize: 11, color: '#777', fontFamily: MONO, letterSpacing: '0.06em' }}>{title.toUpperCase()}</div>
        <Badge label={String(count)} color="#777" />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 8 }}>
        {children}
      </div>
    </div>
  );
}

function ReasoningSurface({
  query, status, reasoning, conflicts, loading, limit, force,
  onQueryChange, onLimitChange, onForceChange, onSearch, onBuild,
}: {
  query: string;
  status: LocalReasoningStatusResponse | null;
  reasoning: LocalReasoningSearchResponse | null;
  conflicts: LocalReasoningConflictsResponse | null;
  loading: boolean;
  limit: number;
  force: boolean;
  onQueryChange: (value: string) => void;
  onLimitChange: (value: number) => void;
  onForceChange: (value: boolean) => void;
  onSearch: () => void;
  onBuild: () => void;
}) {
  const groups = reasoning?.items ?? [];
  const conflictItems = conflicts?.items ?? [];
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 360px', gap: 18, alignItems: 'start' }}>
      <Panel>
        <div style={{ display: 'flex', gap: 8, padding: '0 12px 12px', flexWrap: 'wrap' }}>
          <input
            value={query}
            onChange={e => onQueryChange(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') onSearch(); }}
            placeholder="Search resolved facts, conflicts, metrics, or decisions"
            style={{
              flex: 1, minWidth: 0, background: '#050505', border: '1px solid #1b1b1b',
              color: '#ddd', borderRadius: 6, padding: '8px 10px', fontSize: 12,
            }}
          />
          <button onClick={onSearch} style={buttonStyle('primary', false)}>Search</button>
        </div>
        <div style={{ display: 'flex', gap: 8, padding: '0 12px 12px', flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            type="number"
            min={1}
            max={50000}
            value={limit}
            onChange={e => onLimitChange(Math.max(1, Math.min(50000, Number(e.target.value) || 1)))}
            style={{ ...selectStyle, width: 96 }}
            title="Fact limit"
          />
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#aaa', fontSize: 12 }}>
            <input type="checkbox" checked={force} onChange={e => onForceChange(e.target.checked)} />
            Force
          </label>
          <button onClick={onBuild} disabled={loading} style={buttonStyle('secondary', loading)}>
            {loading ? 'Reasoning...' : 'Build reasoning'}
          </button>
        </div>
        <div style={{ padding: '0 12px 12px', fontSize: 12, color: '#777', lineHeight: 1.45 }}>
          Reasoning groups matching semantic facts, detects conflicts, and chooses a preferred claim only when the source trail is strong enough. It uses approved local semantic rows and does not call Ollama to judge conflicts.
        </div>
        {groups.length === 0 ? (
          <EmptyState
            title="No reasoning state built yet"
            hint="Build semantics first, then build reasoning to group facts and find conflicts."
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '0 12px 12px' }}>
            <ObjectSection title="Resolved and grouped facts" count={groups.length}>
              {groups.slice(0, 80).map(group => <ReasoningCard key={group.group_id} group={group} />)}
            </ObjectSection>
            <ObjectSection title="Conflicts" count={conflictItems.length}>
              {conflictItems.slice(0, 40).map(group => <ReasoningCard key={`conflict-${group.group_id}`} group={group} conflict />)}
            </ObjectSection>
          </div>
        )}
      </Panel>
      <Panel sticky>
        <div style={{ padding: '0 18px' }}>
          <DetailRow k="GROUPS" v={String(status?.groups ?? 0)} />
          <DetailRow k="CLAIMS" v={String(status?.claims ?? 0)} />
          <DetailRow k="RESOLVED" v={String(status?.resolved ?? 0)} />
          <DetailRow k="UNRESOLVED" v={String(status?.unresolved ?? 0)} />
          <DetailRow k="CONFLICTS" v={String(status?.conflicts ?? 0)} />
          <DetailRow k="LAST BUILD" v={status?.last_built_at ? new Date(status.last_built_at * 1000).toLocaleString() : '-'} />
          <SectionLabel text="HOW IT DECIDES" />
          <div style={{ fontSize: 12, color: '#777', lineHeight: 1.45, marginTop: 8 }}>
            SHAIL prefers approved, non-deleted files, newer versions, non-duplicate sources, stronger extraction confidence, and repeated matching claims. If the top claims are too close, it marks the group unresolved.
          </div>
        </div>
      </Panel>
    </div>
  );
}

function ReasoningCard({ group, conflict = false }: { group: LocalReasoningGroup; conflict?: boolean }) {
  const preferred = group.preferred_claim;
  const color = group.confidence === 'high' ? '#22c55e' : group.confidence === 'medium' ? '#fbbf24' : '#fb7185';
  return (
    <div style={{ border: '1px solid #151515', borderRadius: 7, background: '#050505', padding: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 9, color: conflict ? '#fb7185' : '#f97316', fontFamily: MONO, letterSpacing: '0.06em' }}>
          {conflict ? 'CONFLICT' : group.status.replaceAll('_', ' ').toUpperCase()}
        </span>
        <span style={{ fontSize: 10, color, fontFamily: MONO }}>{group.confidence}</span>
      </div>
      <div style={{ fontSize: 13, color: '#eee', fontWeight: 500, wordBreak: 'break-word' }}>{group.label}</div>
      {preferred ? (
        <div style={{ marginTop: 8 }}>
          <Badge label="preferred" color="#22c55e" />
          <div style={{ fontSize: 12, color: '#ccc', marginTop: 6, wordBreak: 'break-word' }}>
            {preferred.value || preferred.value_norm}
          </div>
          <div style={{ fontSize: 10, color: '#555', fontFamily: MONO, marginTop: 5, wordBreak: 'break-all' }}>{preferred.path}</div>
        </div>
      ) : (
        <div style={{ fontSize: 12, color: '#ef9a9a', marginTop: 8 }}>No preferred claim selected.</div>
      )}
      {group.reason && <div style={{ fontSize: 11, color: '#aaa', marginTop: 8, lineHeight: 1.4 }}>{group.reason}</div>}
      {group.competing_claims.length > 0 && (
        <div style={{ marginTop: 10, display: 'grid', gap: 6 }}>
          {group.competing_claims.slice(0, 3).map(claim => (
            <div key={claim.claim_id} style={{ borderTop: '1px solid #151515', paddingTop: 6 }}>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 4 }}>
                <Badge label={claim.value || claim.value_norm} color={claim.value_norm === preferred?.value_norm ? '#777' : '#fb7185'} />
                {claim.is_latest_candidate && <Badge label="latest" color="#22c55e" />}
                {claim.is_duplicate_candidate && <Badge label="duplicate" color="#fb7185" />}
              </div>
              <div style={{ fontSize: 10, color: '#555', fontFamily: MONO, wordBreak: 'break-all' }}>{claim.path}</div>
            </div>
          ))}
        </div>
      )}
      {group.warnings.length > 0 && (
        <div style={{ fontSize: 11, color: '#fbbf24', marginTop: 8, lineHeight: 1.4 }}>{group.warnings.slice(0, 2).join(' ')}</div>
      )}
    </div>
  );
}

function IntelligenceSurface({
  query, packet, status, loading, k, includeAnswer, includeGraph,
  onQueryChange, onKChange, onIncludeAnswerChange, onIncludeGraphChange, onBuild,
}: {
  query: string;
  packet: LocalIntelligencePacketResponse | null;
  status: LocalIntelligenceStatusResponse | null;
  loading: boolean;
  k: number;
  includeAnswer: boolean;
  includeGraph: boolean;
  onQueryChange: (value: string) => void;
  onKChange: (value: number) => void;
  onIncludeAnswerChange: (value: boolean) => void;
  onIncludeGraphChange: (value: boolean) => void;
  onBuild: () => void;
}) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 360px', gap: 18, alignItems: 'start' }}>
      <Panel>
        <div style={{ display: 'flex', gap: 8, padding: '0 12px 12px', flexWrap: 'wrap' }}>
          <input
            value={query}
            onChange={e => onQueryChange(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') onBuild(); }}
            placeholder="Question or topic for a USSF intelligence packet"
            style={{
              flex: '1 1 360px', minWidth: 0, background: '#050505', border: '1px solid #1b1b1b',
              color: '#ddd', borderRadius: 6, padding: '8px 10px', fontSize: 12,
            }}
          />
          <input
            type="number"
            value={k}
            min={1}
            max={50}
            onChange={e => onKChange(Math.max(1, Math.min(50, Number(e.target.value) || 12)))}
            style={{ width: 70, background: '#050505', border: '1px solid #1b1b1b', color: '#ddd', borderRadius: 6, padding: '8px 10px', fontSize: 12 }}
          />
          <label style={checkLabelStyle}>
            <input type="checkbox" checked={includeAnswer} onChange={e => onIncludeAnswerChange(e.target.checked)} />
            answer
          </label>
          <label style={checkLabelStyle}>
            <input type="checkbox" checked={includeGraph} onChange={e => onIncludeGraphChange(e.target.checked)} />
            graph
          </label>
          <button onClick={onBuild} disabled={loading} style={buttonStyle('primary', loading)}>
            {loading ? 'Building...' : 'Build packet'}
          </button>
        </div>

        {!packet ? (
          <EmptyState
            title="No intelligence packet yet"
            hint="Build a packet to see answer, canonical facts, conflicts, gaps, actions, and sources."
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '0 12px 12px' }}>
            <div style={{ border: '1px solid #202020', borderRadius: 7, background: '#090909', padding: 14 }}>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                <Badge label={`confidence: ${packet.confidence}`} color={confidenceColor(packet.confidence)} />
                <Badge label={`facts: ${packet.canonical_facts.length}`} color="#22c55e" />
                <Badge label={`conflicts: ${packet.conflicts.length}`} color="#fb7185" />
                <Badge label={`gaps: ${packet.gaps.length}`} color="#fbbf24" />
              </div>
              <div style={{ fontSize: 13, color: '#e6e6e6', lineHeight: 1.55 }}>{packet.answer}</div>
            </div>

            <SectionLabel text="CANONICAL FACTS" />
            {packet.canonical_facts.length === 0 ? (
              <EmptyState title="No canonical facts" hint="SHAIL did not find resolved or raw semantic facts for this packet." />
            ) : packet.canonical_facts.slice(0, 12).map(fact => <CanonicalFactCard key={fact.fact_id} fact={fact} />)}

            <SectionLabel text="CONFLICTS" />
            {packet.conflicts.length === 0 ? (
              <div style={{ fontSize: 12, color: '#777' }}>No conflicts attached.</div>
            ) : packet.conflicts.slice(0, 8).map((conflict, idx) => (
              <SmallInfoCard key={String(conflict.group_id || idx)} title={String(conflict.label || 'Conflict')} tone="danger">
                <div>{String(conflict.status || 'conflict')} / {String(conflict.confidence || 'unknown')}</div>
                {conflict.reason && <div style={{ marginTop: 5 }}>{String(conflict.reason)}</div>}
              </SmallInfoCard>
            ))}

            <SectionLabel text="GAPS" />
            {packet.gaps.length === 0 ? (
              <div style={{ fontSize: 12, color: '#777' }}>No major gaps detected.</div>
            ) : packet.gaps.slice(0, 8).map((gap, idx) => (
              <SmallInfoCard key={`${gap.type || 'gap'}-${idx}`} title={String(gap.type || 'gap')} tone="warn">
                {String(gap.message || '')}
              </SmallInfoCard>
            ))}
          </div>
        )}
      </Panel>
      <Panel sticky>
        <div style={{ padding: '0 18px' }}>
          <DetailRow k="PACKETS" v={String(status?.packets ?? 0)} />
          <DetailRow k="LLM" v={status?.llm_synthesis_enabled ? 'enabled' : 'disabled'} />
          <DetailRow k="MODEL" v={status?.model || '-'} />
          {packet && (
            <>
              <DetailRow k="PACKET" v={packet.packet_id} />
              <DetailRow k="BUNDLE" v={packet.evidence_bundle_id} />
              <SectionLabel text="NEXT ACTIONS" />
              {packet.recommended_next_actions.length === 0 ? (
                <div style={{ fontSize: 12, color: '#777', marginTop: 8 }}>No actions suggested.</div>
              ) : packet.recommended_next_actions.map(action => (
                <div key={action} style={{ fontSize: 12, color: '#ccc', lineHeight: 1.4, marginTop: 8 }}>{action}</div>
              ))}
              <SectionLabel text="SOURCE MAP" />
              {packet.source_map.slice(0, 12).map((source, idx) => (
                <div key={`${source.file_id || idx}`} style={{ border: '1px solid #151515', borderRadius: 7, padding: 9, background: '#050505', marginTop: 8 }}>
                  <div style={{ fontSize: 12, color: '#ccc', wordBreak: 'break-word' }}>{String(source.title || source.file_id || 'source')}</div>
                  <div style={{ fontSize: 10, color: source.suppressed ? '#fb7185' : '#777', fontFamily: MONO, marginTop: 4 }}>
                    {String(source.role || 'source')} {source.is_latest_candidate ? '/ latest' : ''}
                  </div>
                </div>
              ))}
              <SectionLabel text="WARNINGS" />
              {packet.warnings.length === 0 ? (
                <div style={{ fontSize: 12, color: '#777', marginTop: 8 }}>No warnings.</div>
              ) : packet.warnings.slice(0, 8).map(w => (
                <div key={w} style={{ fontSize: 12, color: '#ef9a9a', lineHeight: 1.4, marginTop: 8 }}>{w}</div>
              ))}
            </>
          )}
        </div>
      </Panel>
    </div>
  );
}

function CanonicalFactCard({ fact }: { fact: LocalCanonicalFact }) {
  const title = [fact.entity, fact.attribute].filter(Boolean).join(' ') || fact.fact_id;
  return (
    <div style={{ border: '1px solid #151515', borderRadius: 7, background: '#050505', padding: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, marginBottom: 6 }}>
        <div style={{ fontSize: 13, color: '#eee', fontWeight: 500, wordBreak: 'break-word' }}>{title}</div>
        <span style={{ fontSize: 10, color: factStatusColor(fact.status), fontFamily: MONO }}>{fact.status}</span>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        <Badge label={fact.confidence} color={confidenceColor(fact.confidence)} />
        {fact.period && <Badge label={String(fact.period)} color="#777" />}
        {fact.competing_claims.length > 0 && <Badge label={`${fact.competing_claims.length} competing`} color="#fb7185" />}
      </div>
      <div style={{ fontSize: 13, color: '#ddd', wordBreak: 'break-word' }}>{String(fact.value ?? 'unknown')}</div>
      {fact.why_this_is_preferred && <div style={{ fontSize: 11, color: '#777', marginTop: 8, lineHeight: 1.4 }}>{fact.why_this_is_preferred}</div>}
    </div>
  );
}

function SmallInfoCard({ title, tone, children }: { title: string; tone: 'danger' | 'warn'; children: React.ReactNode }) {
  const color = tone === 'danger' ? '#fb7185' : '#fbbf24';
  return (
    <div style={{ border: `1px solid ${tone === 'danger' ? '#251515' : '#2a2410'}`, borderRadius: 7, background: '#050505', padding: 10 }}>
      <div style={{ fontSize: 10, color, fontFamily: MONO, marginBottom: 5 }}>{title.toUpperCase()}</div>
      <div style={{ fontSize: 12, color: '#aaa', lineHeight: 1.45 }}>{children}</div>
    </div>
  );
}

function FactCard({ item }: { item: LocalSemanticFact }) {
  const title = [item.entity, item.attribute].filter(Boolean).join(' ') || 'Fact';
  const nodeType = item.unit === '%' ? 'percent_value' : item.unit ? 'money_value' : item.attribute === 'decision' ? 'decision' : item.attribute === 'date' ? 'date' : 'fact';
  return (
    <ObjectCard
      type={nodeType}
      title={title}
      value={item.value || ''}
      path={item.path}
      source={item.source_span || ''}
      confidence={item.confidence}
      extractor={String(item.metadata?.extractor || 'deterministic')}
    />
  );
}

function TaskCard({ item }: { item: LocalSemanticTask }) {
  return (
    <ObjectCard
      type="task"
      title={item.text}
      value={item.due_date ? `due ${item.due_date}` : item.status || ''}
      path={item.path}
      source={item.source_span || ''}
      confidence={item.confidence}
      extractor={String(item.metadata?.extractor || 'deterministic')}
    />
  );
}

function EntityCard({ item }: { item: LocalSemanticEntity }) {
  return (
    <ObjectCard
      type={item.entity_type === 'organization' ? 'organization' : item.entity_type === 'person' ? 'person' : 'entity'}
      title={item.label}
      value={item.entity_type}
      path={item.path}
      source={item.source_span || ''}
      confidence={item.confidence}
      extractor={String(item.metadata?.extractor || 'deterministic')}
    />
  );
}

function ObjectCard({
  type, title, value, path, source, confidence, extractor,
}: {
  type: string;
  title: string;
  value: string;
  path: string;
  source: string;
  confidence: string;
  extractor: string;
}) {
  const color = NODE_COLOR[type] || '#777';
  return (
    <div style={{ border: '1px solid #151515', borderRadius: 7, background: '#050505', padding: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 9, color, fontFamily: MONO, letterSpacing: '0.06em' }}>
          {type.replaceAll('_', ' ').toUpperCase()}
        </span>
        <span style={{ fontSize: 10, color: confidenceColor(confidence), fontFamily: MONO }}>{confidence}</span>
      </div>
      <Badge label={extractor === 'ollama' ? 'ollama' : 'rules'} color={extractor === 'ollama' ? '#c084fc' : '#777'} />
      <div style={{ fontSize: 13, color: '#eee', fontWeight: 500, wordBreak: 'break-word' }}>{title}</div>
      {value && <div style={{ fontSize: 12, color: '#aaa', marginTop: 5, wordBreak: 'break-word' }}>{value}</div>}
      <div style={{ fontSize: 10, color: '#555', fontFamily: MONO, marginTop: 6, wordBreak: 'break-all' }}>{path}</div>
      {source && <div style={{ fontSize: 11, color: '#777', marginTop: 8, lineHeight: 1.4 }}>{source}</div>}
    </div>
  );
}

function EvidenceCard({ item }: { item: LocalEvidenceItem }) {
  return (
    <div style={{ border: '1px solid #151515', borderRadius: 7, background: '#050505', padding: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, marginBottom: 6 }}>
        <div style={{ fontSize: 13, color: '#eee', fontWeight: 500, wordBreak: 'break-word' }}>{item.title}</div>
        <span style={{ fontSize: 10, color: confidenceColor(item.confidence), fontFamily: MONO }}>{item.confidence}</span>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        <Badge label={item.evidence_source === 'graph' ? 'related' : 'primary'} color={item.evidence_source === 'graph' ? '#22c55e' : '#7aa6e0'} />
        <Badge label={`score ${item.score.toFixed(2)}`} color="#777" />
        {item.graph_relation && <Badge label={item.graph_relation} color="#fbbf24" />}
        {item.is_latest_candidate && <Badge label="latest candidate" color="#22c55e" />}
        {item.is_duplicate_candidate && <Badge label="duplicate" color="#fb7185" />}
      </div>
      <div style={{ fontSize: 11, color: '#aaa', marginBottom: 6 }}>{item.reason}</div>
      <div style={{ fontSize: 10, color: '#555', fontFamily: MONO, wordBreak: 'break-all', marginBottom: 8 }}>{item.path}</div>
      <div style={{ fontSize: 12, color: '#aaa', lineHeight: 1.45 }}>{item.snippet}</div>
    </div>
  );
}

function EvidenceInspector({ evidence }: { evidence: LocalEvidenceResponse }) {
  return (
    <div style={{ padding: '0 18px' }}>
      <DetailRow k="BUNDLE" v={evidence.evidence_bundle_id} />
      <DetailRow k="CONFIDENCE" v={evidence.confidence} />
      <DetailRow k="DIRECT" v={String(evidence.direct_matches.length)} />
      <DetailRow k="GRAPH" v={String(evidence.graph_expansions.length)} />
      <DetailRow k="SUPPRESSED" v={String(evidence.suppressed_files.length)} />

      <SectionLabel text="WARNINGS" />
      {[...(evidence.warnings || []), ...(evidence.reasoning_warnings || [])].length === 0 ? (
        <div style={{ fontSize: 12, color: '#777', marginTop: 8 }}>No warnings for this bundle.</div>
      ) : [...(evidence.warnings || []), ...(evidence.reasoning_warnings || [])].map(w => (
        <div key={w} style={{ fontSize: 12, color: '#ef9a9a', lineHeight: 1.4, marginTop: 8 }}>{w}</div>
      ))}

      <SectionLabel text="RESOLVED FACTS" />
      {!evidence.semantic_resolutions?.length ? (
        <div style={{ fontSize: 12, color: '#777', marginTop: 8 }}>No resolved semantic facts attached.</div>
      ) : evidence.semantic_resolutions.slice(0, 5).map(group => (
        <div key={group.group_id} style={{ border: '1px solid #151515', borderRadius: 7, padding: 9, background: '#050505', marginTop: 8 }}>
          <div style={{ fontSize: 12, color: '#ccc', wordBreak: 'break-word' }}>{group.label}</div>
          <div style={{ fontSize: 10, color: '#22c55e', fontFamily: MONO, marginTop: 4 }}>
            {group.preferred_claim?.value || group.preferred_claim?.value_norm || 'preferred'}
          </div>
          {group.reason && <div style={{ fontSize: 11, color: '#777', marginTop: 5, lineHeight: 1.4 }}>{group.reason}</div>}
        </div>
      ))}

      <SectionLabel text="CONFLICTS" />
      {!evidence.semantic_conflicts?.length ? (
        <div style={{ fontSize: 12, color: '#777', marginTop: 8 }}>No semantic conflicts attached.</div>
      ) : evidence.semantic_conflicts.slice(0, 5).map(group => (
        <div key={group.group_id} style={{ border: '1px solid #251515', borderRadius: 7, padding: 9, background: '#080505', marginTop: 8 }}>
          <div style={{ fontSize: 12, color: '#ccc', wordBreak: 'break-word' }}>{group.label}</div>
          <div style={{ fontSize: 10, color: '#fb7185', fontFamily: MONO, marginTop: 4 }}>
            {group.status} / {group.confidence}
          </div>
          {group.reason && <div style={{ fontSize: 11, color: '#777', marginTop: 5, lineHeight: 1.4 }}>{group.reason}</div>}
        </div>
      ))}

      <SectionLabel text="SUPPRESSED FILES" />
      {evidence.suppressed_files.length === 0 ? (
        <div style={{ fontSize: 12, color: '#777', marginTop: 8 }}>No duplicate or overflow files suppressed.</div>
      ) : evidence.suppressed_files.map(item => (
        <div key={item.id} style={{ border: '1px solid #151515', borderRadius: 7, padding: 9, background: '#050505', marginTop: 8 }}>
          <div style={{ fontSize: 12, color: '#ccc', wordBreak: 'break-word' }}>{item.title}</div>
          <div style={{ fontSize: 10, color: '#666', fontFamily: MONO, marginTop: 4 }}>{item.reason}</div>
        </div>
      ))}
    </div>
  );
}

function AnswerInspector({ answer, evidence }: { answer: LocalAnswerResponse; evidence: LocalEvidenceResponse | null }) {
  return (
    <div style={{ padding: '0 18px' }}>
      <DetailRow k="ANSWER" v={answer.confidence} />
      <DetailRow k="BUNDLE" v={answer.evidence_bundle_id} />
      <DetailRow k="QUALITY" v={`${Math.round((answer.quality_score || 0) * 100)}%`} />
      <DetailRow k="CITATIONS" v={String(answer.citations.length)} />
      {evidence && <DetailRow k="SELECTED" v={String(evidence.selected_files.length)} />}

      <SectionLabel text="QUALITY SIGNALS" />
      {Object.entries(answer.quality_signals || {}).slice(0, 10).map(([key, value]) => (
        <DetailRow key={key} k={key.replaceAll('_', ' ').toUpperCase()} v={String(value)} />
      ))}

      <SectionLabel text="EVIDENCE SUMMARY" />
      {answer.evidence_summary.length === 0 ? (
        <div style={{ fontSize: 12, color: '#777', marginTop: 8 }}>No files selected for this answer.</div>
      ) : answer.evidence_summary.slice(0, 6).map((item, idx) => (
        <div key={`${item.file_id || idx}`} style={{ border: '1px solid #151515', borderRadius: 7, padding: 9, background: '#050505', marginTop: 8 }}>
          <div style={{ fontSize: 12, color: '#ccc', wordBreak: 'break-word' }}>{String(item.title || item.file_id || 'file')}</div>
          <div style={{ fontSize: 10, color: '#777', fontFamily: MONO, marginTop: 4 }}>{String(item.reason || '')}</div>
        </div>
      ))}

      <SectionLabel text="RESOLVED FACTS" />
      {answer.semantic_resolutions.length === 0 ? (
        <div style={{ fontSize: 12, color: '#777', marginTop: 8 }}>No resolved facts used.</div>
      ) : answer.semantic_resolutions.slice(0, 5).map(group => (
        <div key={group.group_id} style={{ border: '1px solid #151515', borderRadius: 7, padding: 9, background: '#050505', marginTop: 8 }}>
          <div style={{ fontSize: 12, color: '#ccc', wordBreak: 'break-word' }}>{group.label}</div>
          <div style={{ fontSize: 10, color: '#22c55e', fontFamily: MONO, marginTop: 4 }}>
            {group.preferred_claim?.value || group.preferred_claim?.value_norm || group.confidence}
          </div>
        </div>
      ))}

      <SectionLabel text="CONFLICTS" />
      {answer.semantic_conflicts.length === 0 ? (
        <div style={{ fontSize: 12, color: '#777', marginTop: 8 }}>No conflicts considered.</div>
      ) : answer.semantic_conflicts.slice(0, 5).map(group => (
        <div key={group.group_id} style={{ border: '1px solid #251515', borderRadius: 7, padding: 9, background: '#080505', marginTop: 8 }}>
          <div style={{ fontSize: 12, color: '#ccc', wordBreak: 'break-word' }}>{group.label}</div>
          <div style={{ fontSize: 10, color: '#fb7185', fontFamily: MONO, marginTop: 4 }}>{group.status} / {group.confidence}</div>
        </div>
      ))}
    </div>
  );
}

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span style={{
      border: `1px solid ${color}44`, color, borderRadius: 999,
      fontSize: 10, fontFamily: MONO, padding: '2px 7px',
    }}>{label}</span>
  );
}

function SectionLabel({ text }: { text: string }) {
  return (
    <div style={{ marginTop: 18, fontSize: 10, color: '#555', fontFamily: MONO, letterSpacing: '0.06em' }}>
      {text}
    </div>
  );
}

function Segmented({ value, onChange }: { value: ViewMode; onChange: (v: ViewMode) => void }) {
  return (
    <div style={{ display: 'flex', border: '1px solid #1f1f1f', borderRadius: 7, overflow: 'hidden' }}>
      {(['graph', 'evidence', 'objects', 'reasoning', 'intelligence', 'tree'] as ViewMode[]).map(item => (
        <button
          key={item}
          onClick={() => onChange(item)}
          style={{
            border: 'none', borderRight: item !== 'tree' ? '1px solid #1f1f1f' : 'none',
            background: value === item ? '#f5f5f5' : '#050505',
            color: value === item ? '#000' : '#888',
            padding: '7px 12px', fontSize: 12, cursor: 'pointer',
          }}
        >
          {item === 'graph' ? 'Graph' : item === 'evidence' ? 'Evidence' : item === 'objects' ? 'Objects' : item === 'reasoning' ? 'Reasoning' : item === 'intelligence' ? 'Intelligence' : 'Tree'}
        </button>
      ))}
    </div>
  );
}

function Panel({ children, sticky = false }: { children: React.ReactNode; sticky?: boolean }) {
  return (
    <div style={{
      background: '#0a0a0a', border: '1px solid #161616', borderRadius: 8,
      padding: '12px 0', minHeight: 400, position: sticky ? 'sticky' : 'relative', top: sticky ? 0 : undefined,
    }}>
      {children}
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: number | string; color?: string }) {
  return (
    <div style={{ background: '#0a0a0a', border: '1px solid #161616', borderRadius: 8, padding: '12px 16px', minWidth: 110 }}>
      <div style={{ fontSize: 9, color: color || '#555', fontFamily: MONO, letterSpacing: '0.08em', marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 500, color: '#ccc' }}>{value}</div>
    </div>
  );
}

function TreeRow({
  node, depth, expanded, childrenByPath, onToggle, selected,
}: {
  node: PathTreeNode;
  depth: number;
  expanded: Set<string>;
  childrenByPath: Record<string, PathTreeNode[]>;
  onToggle: (n: PathTreeNode) => void;
  selected: string | null;
}) {
  const open = expanded.has(node.id);
  const indent = depth * 16;
  const isSel = selected === node.id;
  return (
    <>
      <div
        onClick={() => onToggle(node)}
        style={{
          padding: `4px 14px 4px ${14 + indent}px`,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontFamily: MONO,
          fontSize: 12,
          color: isSel ? '#fff' : node.is_dir ? '#ccc' : '#888',
          background: isSel ? '#101820' : 'transparent',
        }}
      >
        <span style={{ color: '#555', width: 10 }}>{node.is_dir ? (open ? 'v' : '>') : ' '}</span>
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {node.is_dir ? `${node.name}/` : node.name}
        </span>
        {!node.is_dir && node.kind && (
          <span style={{ fontSize: 9, color: KIND_COLOR[node.kind] || '#666', fontFamily: MONO, letterSpacing: '0.05em' }}>
            {node.kind.toUpperCase()}
          </span>
        )}
        {node.is_dir && node.child_count > 0 && (
          <span style={{ fontSize: 10, color: '#555' }}>{node.child_count}</span>
        )}
      </div>
      {open && childrenByPath[node.id]?.map(child => (
        <TreeRow
          key={child.id}
          node={child}
          depth={depth + 1}
          expanded={expanded}
          childrenByPath={childrenByPath}
          onToggle={onToggle}
          selected={selected}
        />
      ))}
    </>
  );
}

function GraphNodeButton({
  node, relationCount, selected, onClick,
}: {
  node: LocalGraphNode;
  relationCount: number;
  selected: boolean;
  onClick: () => void;
}) {
  const color = NODE_COLOR[node.type] || '#666';
  return (
    <button
      onClick={onClick}
      style={{
        textAlign: 'left', background: selected ? '#101820' : '#050505', border: selected ? '1px solid #1f3a4a' : '1px solid #151515',
        borderRadius: 7, padding: 10, color: '#ddd', cursor: 'pointer', minHeight: 76,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 9, color, fontFamily: MONO, letterSpacing: '0.06em' }}>
          {node.type.replaceAll('_', ' ').toUpperCase()}
        </span>
        <span style={{ fontSize: 10, color: '#555', fontFamily: MONO }}>{relationCount}</span>
      </div>
      <div style={{ fontSize: 12, color: '#ddd', lineHeight: 1.35, wordBreak: 'break-word' }}>{nodeTitle(node)}</div>
      {(node.path || node.uri) && (
        <div style={{ marginTop: 6, fontSize: 10, color: '#555', fontFamily: MONO, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {node.path || node.uri}
        </div>
      )}
    </button>
  );
}

function FileDetail({
  node, refreshing, onRefresh, onOpen,
}: {
  node: PathTreeNode;
  refreshing: boolean;
  onRefresh: () => void;
  onOpen: () => void;
}) {
  const sizeKb = node.size ? (node.size / 1024).toFixed(1) : '-';
  const mtime = node.mtime ? new Date(node.mtime * 1000).toLocaleString() : '-';
  return (
    <div style={{ padding: '0 18px' }}>
      <div style={{ fontSize: 14, fontWeight: 500, color: '#fff', marginBottom: 8, wordBreak: 'break-word' }}>{node.name}</div>
      <div style={{ fontSize: 10, color: '#666', fontFamily: MONO, wordBreak: 'break-all', marginBottom: 12 }}>{node.id}</div>
      <DetailRow k="KIND" v={node.kind || 'other'} />
      <DetailRow k="SIZE" v={`${sizeKb} KB`} />
      <DetailRow k="MODIFIED" v={mtime} />
      <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap' }}>
        <button onClick={onOpen} style={buttonStyle('primary', false)}>Reveal in Finder</button>
        <button onClick={onRefresh} disabled={refreshing} style={buttonStyle('secondary', refreshing)}>
          {refreshing ? 'Refreshing...' : 'Refresh pointer'}
        </button>
      </div>
    </div>
  );
}

function GraphDetail({
  node, relations, nodeById,
}: {
  node: LocalGraphNode;
  relations: LocalGraphRelation[];
  nodeById: Map<string, LocalGraphNode>;
}) {
  return (
    <div style={{ padding: '0 18px' }}>
      <div style={{ fontSize: 9, color: NODE_COLOR[node.type] || '#666', fontFamily: MONO, letterSpacing: '0.06em', marginBottom: 6 }}>
        {node.type.replaceAll('_', ' ').toUpperCase()}
      </div>
      <div style={{ fontSize: 15, fontWeight: 500, color: '#fff', marginBottom: 8, wordBreak: 'break-word' }}>{nodeTitle(node)}</div>
      <div style={{ fontSize: 10, color: '#666', fontFamily: MONO, wordBreak: 'break-all', marginBottom: 12 }}>{node.id}</div>
      {(node.path || node.uri) && <DetailRow k="PATH" v={String(node.path || node.uri)} />}
      <DetailRow k="PRIVACY" v={node.privacy_state || 'allowed'} />
      <DetailRow k="RELATIONS" v={String(relations.length)} />
      <div style={{ marginTop: 16, fontSize: 10, color: '#555', fontFamily: MONO, letterSpacing: '0.06em' }}>NEIGHBORS</div>
      <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {relations.length === 0 ? (
          <div style={{ fontSize: 12, color: '#777' }}>No relationships loaded for this node.</div>
        ) : relations.slice(0, 40).map(rel => {
          const otherId = rel.source_id === node.id ? rel.target_id : rel.source_id;
          const other = nodeById.get(otherId);
          return (
            <div key={`${rel.source_id}|${rel.target_id}|${rel.relation}`} style={{ border: '1px solid #151515', borderRadius: 7, padding: 9, background: '#050505' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 5 }}>
                <span style={{ fontSize: 10, color: '#7aa6e0', fontFamily: MONO }}>{rel.relation}</span>
                <span style={{ fontSize: 10, color: '#555', fontFamily: MONO }}>{rel.confidence || 'INFERRED'}</span>
              </div>
              <div style={{ fontSize: 12, color: '#ccc', wordBreak: 'break-word' }}>{other ? nodeTitle(other) : otherId}</div>
              {rel.evidence && <div style={{ marginTop: 5, fontSize: 10, color: '#666', fontFamily: MONO, wordBreak: 'break-word' }}>{rel.evidence}</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DetailRow({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 14, padding: '6px 0', borderBottom: '1px solid #131313' }}>
      <span style={{ fontSize: 10, color: '#555', fontFamily: MONO, letterSpacing: '0.06em' }}>{k}</span>
      <span style={{ fontSize: 11, color: '#aaa', fontFamily: MONO, textAlign: 'right', wordBreak: 'break-word' }}>{v}</span>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: 9, color: '#555', fontFamily: MONO, letterSpacing: '0.06em' }}>{label}</div>
      <div style={{ fontSize: 13, color: '#ddd', fontFamily: MONO, overflow: 'hidden', textOverflow: 'ellipsis' }}>{value}</div>
    </div>
  );
}

function nodeTitle(node: LocalGraphNode) {
  return String(node.title || node.label || node.uri || node.id || 'Untitled');
}

function confidenceColor(confidence: string) {
  if (confidence === 'high') return '#22c55e';
  if (confidence === 'medium') return '#fbbf24';
  if (confidence === 'EXTRACTED') return '#22c55e';
  if (confidence === 'INFERRED') return '#fbbf24';
  return '#fb7185';
}

function factStatusColor(status: string) {
  if (status === 'accepted') return '#22c55e';
  if (status === 'conflicted' || status === 'unresolved') return '#fb7185';
  if (status === 'stale' || status === 'weak') return '#fbbf24';
  return '#777';
}

function entityTotal(status: LocalSemanticsStatusResponse | null) {
  return Object.values(status?.entities || {}).reduce((sum, value) => sum + value, 0);
}

function readableGraphError(error: unknown) {
  const msg = error instanceof Error ? error.message : String(error);
  if (msg.includes('404') || msg.includes('Not Found')) {
    return 'Graphify backend routes are not available from this running backend. Restart SHAIL backend so the new /local-rag graph, evidence, and semantics APIs are loaded.';
  }
  return msg;
}

const selectStyle: React.CSSProperties = {
  background: '#050505',
  border: '1px solid #1b1b1b',
  color: '#ddd',
  borderRadius: 6,
  padding: '7px 9px',
  fontSize: 12,
};

const checkLabelStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  color: '#888',
  fontSize: 12,
  border: '1px solid #1b1b1b',
  borderRadius: 6,
  padding: '7px 9px',
  background: '#050505',
};

function buttonStyle(kind: 'primary' | 'secondary', busy: boolean): React.CSSProperties {
  return {
    padding: '7px 12px',
    borderRadius: 6,
    fontSize: 12,
    fontWeight: 500,
    cursor: busy ? 'wait' : 'pointer',
    background: kind === 'primary' ? '#f5f5f5' : 'transparent',
    color: kind === 'primary' ? '#000' : '#7aa6e0',
    border: kind === 'primary' ? 'none' : '1px solid #1f3a4a',
  };
}
