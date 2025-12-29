import { useState, useEffect } from 'react';
import WorkflowGraph from './WorkflowGraph';
import DatasetPanel from './DatasetPanel';
import './BirdsEyeView.css';

/**
 * BirdsEyeView - View 4: Bird's-Eye Workflow View
 * 
 * Features:
 * - React Flow graph visualization
 * - Master LLM (Kimi-K2) at center
 * - Worker LLM nodes (Gemini, ChatGPT)
 * - Software tool nodes
 * - Data nodes
 * - Interactive nodes (click to drill down)
 * - Right-side dataset panel
 * - Gestures (3-finger swipe, pinch zoom)
 */
function BirdsEyeView({ workflow, onNodeClick, onSwipeDown }) {
  const [selectedNode, setSelectedNode] = useState(null);
  const [zoom, setZoom] = useState(1);

  const handleNodeClick = (nodeId) => {
    setSelectedNode(nodeId);
    if (onNodeClick) {
      onNodeClick(nodeId);
    }
  };

  return (
    <div className="birdseye-view">
      {/* Main Graph Area */}
      <div className="birdseye-graph-container">
        <WorkflowGraph
          workflow={workflow}
          onNodeClick={handleNodeClick}
          selectedNode={selectedNode}
          zoom={zoom}
        />
      </div>

      {/* Dataset Panel */}
      <div className="birdseye-dataset-panel">
        <DatasetPanel selectedNode={selectedNode} />
      </div>
    </div>
  );
}

export default BirdsEyeView;
