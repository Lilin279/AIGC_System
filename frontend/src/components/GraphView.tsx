import { useEffect, useMemo, useRef, useState } from 'react';
import { Graph as G6Graph } from '@antv/g6';
import { Search, X } from 'lucide-react';
import type { KnowledgeGraph, KnowledgeNode } from '../types';

interface GraphViewProps {
  graph: KnowledgeGraph;
  selectedNodeId?: string;
  pathEdgeIds: string[];
  onSelectNode: (node: KnowledgeNode) => void;
}

const relationColor: Record<string, string> = {
  contains: '#2f80ed',
  prerequisite: '#f2994a',
  related: '#27ae60',
};

export default function GraphView({ graph, selectedNodeId, pathEdgeIds, onSelectNode }: GraphViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const pendingFocusRef = useRef<string | null>(null);
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  const hasQuery = debouncedQuery !== '';
  const matchIds = useMemo(() => {
    const term = debouncedQuery.toLowerCase();
    if (!term) return null;
    const ids = new Set<string>();
    for (const node of graph.nodes) {
      if (node.name.toLowerCase().includes(term)) ids.add(node.id);
    }
    if (ids.size) return ids;
    for (const node of graph.nodes) {
      if (node.definition.toLowerCase().includes(term) || node.example.toLowerCase().includes(term)) {
        ids.add(node.id);
      }
    }
    return ids;
  }, [graph, debouncedQuery]);

  const results = useMemo(() => {
    if (!query.trim()) return [];
    const term = query.trim().toLowerCase();
    const byName = graph.nodes.filter((node) => node.name.toLowerCase().includes(term));
    const byContent = graph.nodes.filter((node) =>
      !node.name.toLowerCase().includes(term)
      && (node.definition.toLowerCase().includes(term) || node.example.toLowerCase().includes(term)),
    );
    return [...byName, ...byContent].slice(0, 8);
  }, [graph, query]);

  useEffect(() => {
    if (!containerRef.current) return undefined;

    const instance = new G6Graph({
      container: containerRef.current,
      autoFit: 'view',
      autoResize: true,
      data: {
        nodes: graph.nodes.map((node) => ({
          id: node.id,
          data: {
            label: node.name,
            type: node.type,
            mastered: node.mastered,
            selected: node.id === selectedNodeId,
            matched: hasQuery && matchIds?.has(node.id),
            dimmed: hasQuery && !matchIds?.has(node.id),
          },
        })),
        edges: graph.edges.map((edge) => ({
          id: edge.id,
          source: edge.source,
          target: edge.target,
          data: {
            label: edge.label,
            relation: edge.relation,
            inPath: pathEdgeIds.includes(edge.id),
            dimmed: hasQuery,
          },
        })),
      },
      layout: {
        type: 'force',
        preventOverlap: true,
        linkDistance: 130,
      },
      node: {
        style: {
          size: 42,
          fill: (datum: any) => {
            if (datum.data?.matched) return '#ffe08a';
            if (datum.data?.mastered) return '#d6f5e5';
            if (datum.data?.selected) return '#ffe4c7';
            return '#eef4ff';
          },
          stroke: (datum: any) => {
            if (datum.data?.matched) return '#f2994a';
            if (datum.data?.selected) return '#f2994a';
            return '#365f91';
          },
          lineWidth: (datum: any) => (datum.data?.selected || datum.data?.matched ? 3 : 1.5),
          opacity: (datum: any) => (datum.data?.dimmed ? 0.22 : 1),
          labelText: (datum: any) => datum.data?.label,
          labelPlacement: 'bottom',
          labelFill: '#1f2937',
          labelFontSize: 12,
        },
      },
      edge: {
        style: {
          stroke: (datum: any) => relationColor[datum.data?.relation] ?? '#97a2b0',
          lineWidth: (datum: any) => (datum.data?.inPath ? 3 : 1.3),
          opacity: (datum: any) => (datum.data?.dimmed ? 0.12 : 1),
          endArrow: true,
          labelText: (datum: any) => datum.data?.label,
          labelFill: '#4b5563',
          labelFontSize: 10,
        },
      },
      behaviors: ['drag-canvas', 'zoom-canvas', 'drag-element'],
    });

    instance.on?.('node:click', (event: any) => {
      const id = event?.target?.id ?? event?.item?.getID?.();
      const node = graph.nodes.find((item) => item.id === id);
      if (node) onSelectNode(node);
    });

    let renderFinished = false;
    let disposed = false;
    void instance.render().then(() => {
      renderFinished = true;
      if (disposed) { instance.destroy(); return; }
      const focusId = pendingFocusRef.current;
      if (focusId) {
        pendingFocusRef.current = null;
        try { instance.focusElement(focusId); } catch { /* 聚焦失败不影响使用 */ }
      }
    });

    return () => {
      disposed = true;
      if (renderFinished) instance.destroy();
    };
  }, [graph, onSelectNode, pathEdgeIds, selectedNodeId, hasQuery, matchIds]);

  const pickResult = (node: KnowledgeNode) => {
    pendingFocusRef.current = node.id;
    setQuery('');
    onSelectNode(node);
  };

  return (
    <div className="graph-container">
      <div ref={containerRef} className="graph-canvas" />
      <div className="graph-search">
        <Search size={15} />
        <input
          placeholder="搜索知识点"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && results.length) pickResult(results[0]);
            if (event.key === 'Escape') setQuery('');
          }}
        />
        {query && <button className="graph-search-clear" title="清空搜索" onClick={() => setQuery('')}><X size={14} /></button>}
        {query.trim() && (
          <div className="graph-search-results">
            {results.length ? results.map((node) => (
              <button key={node.id} onClick={() => pickResult(node)}>
                <span className="node-type">{node.type}</span><span className="result-name">{node.name}</span>
              </button>
            )) : <p>未找到匹配知识点</p>}
          </div>
        )}
      </div>
    </div>
  );
}
