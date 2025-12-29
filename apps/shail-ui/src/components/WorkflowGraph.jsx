import { useState, useCallback } from 'react';
import './WorkflowGraph.css';

/**
 * WorkflowGraph - Graph visualization component
 * 
 * Uses React Flow (or similar) to visualize:
 * - Master LLM node (Kimi-K2) at center
 * - Worker LLM nodes (Gemini, ChatGPT)
 * - Software tool nodes
 * - Data nodes
 * - Input/output nodes
 */
function WorkflowGraph({ workflow, onNodeClick, selectedNode, zoom }) {
  // In full implementation, would use React Flow
  // For now, create a simple visualization

  const nodes = workflow?.nodes || [
    { id: 'master', type: 'master', label: 'Kimi-K2 Master', x: 400, y: 300 },
    { id: 'gemini', type: 'worker', label: 'Gemini Worker', x: 200, y: 200 },
    { id: 'chatgpt', type: 'worker', label: 'ChatGPT Worker', x: 600, y: 200 },
    { id: 'freecad', type: 'tool', label: 'FreeCAD', x: 150, y: 400 },
    { id: 'pybullet', type: 'tool', label: 'PyBullet', x: 650, y: 400 },
  ];

  const edges = workflow?.edges || [
    { from: 'master', to: 'gemini' },
    { from: 'master', to: 'chatgpt' },
    { from: 'gemini', to: 'freecad' },
    { from: 'chatgpt', to: 'pybullet' },
  ];

  return (
    <div className="workflow-graph" style={{ transform: `scale(${zoom})` }}>
      <svg width="100%" height="100%" className="workflow-graph-svg">
        {/* Edges */}
        {edges.map((edge, idx) => (
          <line
            key={idx}
            x1={nodes.find(n => n.id === edge.from)?.x || 0}
            y1={nodes.find(n => n.id === edge.from)?.y || 0}
            x2={nodes.find(n => n.id === edge.to)?.x || 0}
            y2={nodes.find(n => n.id === edge.to)?.y || 0}
            stroke="rgba(59, 130, 246, 0.4)"
            strokeWidth="2"
          />
        ))}

        {/* Nodes */}
        {nodes.map((node) => (
          <g key={node.id}>
            <circle
              cx={node.x}
              cy={node.y}
              r={node.type === 'master' ? 40 : 30}
              fill={node.id === selectedNode ? '#007acc' : getNodeColor(node.type)}
              stroke="white"
              strokeWidth="2"
              className="workflow-node"
              onClick={() => onNodeClick?.(node.id)}
              style={{ cursor: 'pointer' }}
            />
            <text
              x={node.x}
              y={node.y + 5}
              textAnchor="middle"
              fill="white"
              fontSize="12"
              fontWeight="600"
            >
              {node.label}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function getNodeColor(type) {
  const colors = {
    master: '#007acc',
    worker: '#4fc3f7',
    tool: '#66bb6a',
    data: '#ffa726',
  };
  return colors[type] || '#888';
}

export default WorkflowGraph;
