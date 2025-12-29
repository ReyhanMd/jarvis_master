import { useState, useEffect } from 'react';
import SoftwareToolbar from './SoftwareToolbar';
import './AgentSoftwareView.css';

/**
 * AgentSoftwareView - View 3: Agent + Software Interaction View
 * 
 * Features:
 * - Large central live software view (via AccessibilityBridge)
 * - LLM action bubbles overlay
 * - Cursor tracking overlay
 * - Toolbar with workflow summary, software icons, SHAIL status
 */
function AgentSoftwareView({ softwareView, actions = [] }) {
  const [activeSoftware, setActiveSoftware] = useState(null);

  return (
    <div className="agent-software-view">
      {/* Central Software View */}
      <div className="agent-software-main">
        <div className="agent-software-viewport">
          {softwareView ? (
            <div className="agent-software-content">
              {/* Live software view would be rendered here via AccessibilityBridge */}
              <div className="agent-software-placeholder">
                Live Software View
                <div className="agent-software-note">
                  (Connected via AccessibilityBridge)
                </div>
              </div>
            </div>
          ) : (
            <div className="agent-software-empty">
              No software view available
            </div>
          )}

          {/* LLM Action Bubbles Overlay */}
          {actions.map((action, idx) => (
            <div
              key={idx}
              className="agent-action-bubble"
              style={{
                left: action.x || '50%',
                top: action.y || '50%',
              }}
            >
              <div className="agent-action-bubble-content">
                {action.text}
              </div>
            </div>
          ))}

          {/* Cursor Tracking Overlay */}
          <div className="agent-cursor-overlay">
            {/* Cursor position would be tracked here */}
          </div>
        </div>
      </div>

      {/* Toolbar */}
      <SoftwareToolbar
        activeSoftware={activeSoftware}
        workflowSummary="Processing task..."
      />
    </div>
  );
}

export default AgentSoftwareView;
