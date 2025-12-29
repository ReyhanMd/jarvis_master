import { useState } from 'react';
import './DatasetPanel.css';

/**
 * DatasetPanel - Right-side panel for View 4
 * 
 * Features:
 * - Chat logs
 * - Images
 * - CAD files
 * - Simulink models
 * - Logs
 * - Outputs
 * - Past reasoning traces
 */
function DatasetPanel({ selectedNode }) {
  const [activeTab, setActiveTab] = useState('chat');

  const tabs = [
    { id: 'chat', label: 'Chat Logs' },
    { id: 'images', label: 'Images' },
    { id: 'cad', label: 'CAD Files' },
    { id: 'simulink', label: 'Simulink' },
    { id: 'logs', label: 'Logs' },
    { id: 'outputs', label: 'Outputs' },
    { id: 'reasoning', label: 'Reasoning' },
  ];

  return (
    <div className="dataset-panel">
      <div className="dataset-panel-header">
        <h3>Dataset</h3>
        {selectedNode && (
          <span className="dataset-panel-node">Node: {selectedNode}</span>
        )}
      </div>

      <div className="dataset-panel-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`dataset-tab ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="dataset-panel-content">
        {/* Search/Filter */}
        <div className="dataset-search">
          <input
            type="text"
            placeholder="Search..."
            className="dataset-search-input"
          />
        </div>

        {activeTab === 'chat' && (
          <div className="dataset-content">
            {/* Chat log aggregation - would fetch from backend */}
            <div className="dataset-item">
              <div className="dataset-item-header">Chat Logs</div>
              <div className="dataset-item-content">
                <p className="dataset-empty">No chat logs available</p>
              </div>
            </div>
          </div>
        )}
        {activeTab === 'images' && (
          <div className="dataset-content">
            {/* Image storage - would fetch from RAG memory */}
            <div className="dataset-item">
              <div className="dataset-item-header">Images</div>
              <div className="dataset-item-content">
                <p className="dataset-empty">No images available</p>
              </div>
            </div>
          </div>
        )}
        {activeTab === 'cad' && (
          <div className="dataset-content">
            {/* CAD file storage */}
            <div className="dataset-item">
              <div className="dataset-item-header">CAD Files</div>
              <div className="dataset-item-content">
                <p className="dataset-empty">No CAD files available</p>
              </div>
            </div>
          </div>
        )}
        {activeTab === 'simulink' && (
          <div className="dataset-content">
            {/* Simulink model storage */}
            <div className="dataset-item">
              <div className="dataset-item-header">Simulink Models</div>
              <div className="dataset-item-content">
                <p className="dataset-empty">No Simulink models available</p>
              </div>
            </div>
          </div>
        )}
        {activeTab === 'logs' && (
          <div className="dataset-content">
            {/* LLM execution logs */}
            <div className="dataset-item">
              <div className="dataset-item-header">Execution Logs</div>
              <div className="dataset-item-content">
                <p className="dataset-empty">No logs available</p>
              </div>
            </div>
          </div>
        )}
        {activeTab === 'outputs' && (
          <div className="dataset-content">
            {/* Output files */}
            <div className="dataset-item">
              <div className="dataset-item-header">Outputs</div>
              <div className="dataset-item-content">
                <p className="dataset-empty">No outputs available</p>
              </div>
            </div>
          </div>
        )}
        {activeTab === 'reasoning' && (
          <div className="dataset-content">
            {/* Past reasoning traces */}
            <div className="dataset-item">
              <div className="dataset-item-header">Reasoning Traces</div>
              <div className="dataset-item-content">
                <p className="dataset-empty">No reasoning traces available</p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default DatasetPanel;
