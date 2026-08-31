import { useEffect, useRef } from 'react';
import { Graph as G6Graph } from '@antv/g6';
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
  const graphRef = useRef<G6Graph | null>(null);
  const graphDataRef = useRef(graph);
  const selectedNodeIdRef = useRef(selectedNodeId);
  const pathEdgeIdsRef = useRef(pathEdgeIds);
  const onSelectNodeRef = useRef(onSelectNode);

  graphDataRef.current = graph;
  selectedNodeIdRef.current = selectedNodeId;
  pathEdgeIdsRef.current = pathEdgeIds;
  onSelectNodeRef.current = onSelectNode;

  useEffect(() => {
    if (!containerRef.current) return undefined;

    const instance = new G6Graph({
      container: containerRef.current,
      autoFit: 'view',
      autoResize: true,
      data: toG6Data(graphDataRef.current, selectedNodeIdRef.current, pathEdgeIdsRef.current),
      layout: {
        type: 'force',
        preventOverlap: true,
        linkDistance: 130,
      },
      node: {
        style: {
          size: 42,
          fill: (datum: any) => (datum.data?.mastered ? '#d6f5e5' : datum.data?.selected ? '#ffe4c7' : '#eef4ff'),
          stroke: (datum: any) => (datum.data?.selected ? '#f2994a' : '#365f91'),
          lineWidth: (datum: any) => (datum.data?.selected ? 3 : 1.5),
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
          endArrow: true,
          labelText: (datum: any) => datum.data?.label,
          labelFill: '#4b5563',
          labelFontSize: 10,
        },
      },
      behaviors: ['drag-canvas', 'zoom-canvas', 'drag-element'],
    });
    graphRef.current = instance;

    instance.render();
    instance.on?.('node:click', (event: any) => {
      const id = event?.target?.id ?? event?.item?.getID?.();
      const node = graphDataRef.current.nodes.find((item) => item.id === id);
      if (node) onSelectNodeRef.current(node);
    });

    return () => {
      instance.destroy();
      graphRef.current = null;
    };
  }, []);

  useEffect(() => {
    const instance = graphRef.current;
    if (!instance) return;

    // Synchronize changed graph data without calling layout. Existing node
    // positions remain in G6's model, so adding a node or changing mastered
    // status does not restart the force-directed animation.
    instance.stopLayout();
    instance.setData(toG6Data(graph, selectedNodeIdRef.current, pathEdgeIdsRef.current));
    void instance.draw();
  }, [graph]);

  useEffect(() => {
    const instance = graphRef.current;
    if (!instance) return;

    // Update only node data. G6's draw() does not execute layout, so the
    // force-directed positions remain unchanged when selection changes.
    instance.stopLayout();
    instance.updateNodeData(
      instance.getNodeData().map((node) => ({
        id: node.id,
        data: { selected: node.id === selectedNodeId },
      })),
    );
    void instance.draw();
  }, [selectedNodeId]);

  useEffect(() => {
    const instance = graphRef.current;
    if (!instance) return;

    instance.updateEdgeData(
      instance.getEdgeData().map((edge) => ({
        id: edge.id,
        data: { inPath: edge.id != null && pathEdgeIds.includes(String(edge.id)) },
      })),
    );
    void instance.draw();
  }, [pathEdgeIds]);

  return <div ref={containerRef} className="graph-canvas" />;
}

function toG6Data(graph: KnowledgeGraph, selectedNodeId?: string, pathEdgeIds: string[] = []) {
  return {
    nodes: graph.nodes.map((node) => ({
      id: node.id,
      data: {
        label: node.name,
        type: node.type,
        mastered: node.mastered,
        selected: node.id === selectedNodeId,
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
      },
    })),
  };
}
