import './SoftwareToolbar.css';

/**
 * SoftwareToolbar - Toolbar for View 3
 * 
 * Features:
 * - Workflow summary
 * - Software icons (SolidWorks, MATLAB, Simulink, KiCad, etc.)
 * - SHAIL status
 * - "Swipe down to Bird View" handle
 */
function SoftwareToolbar({ activeSoftware, workflowSummary }) {
  const softwareIcons = [
    { name: 'SolidWorks', icon: '⚙️', active: activeSoftware === 'solidworks' },
    { name: 'MATLAB', icon: '📊', active: activeSoftware === 'matlab' },
    { name: 'Simulink', icon: '🔧', active: activeSoftware === 'simulink' },
    { name: 'KiCad', icon: '🔌', active: activeSoftware === 'kicad' },
    { name: 'FreeCAD', icon: '📐', active: activeSoftware === 'freecad' },
  ];

  return (
    <div className="software-toolbar">
      <div className="software-toolbar-content">
        {/* Workflow Summary */}
        <div className="software-toolbar-summary">
          <span className="software-toolbar-label">Workflow:</span>
          <span className="software-toolbar-text">{workflowSummary || 'Idle'}</span>
        </div>

        {/* Software Icons */}
        <div className="software-toolbar-icons">
          {softwareIcons.map((sw, idx) => (
            <div
              key={idx}
              className={`software-icon ${sw.active ? 'active' : ''}`}
              title={sw.name}
            >
              {sw.icon}
            </div>
          ))}
        </div>

        {/* SHAIL Status */}
        <div className="software-toolbar-status">
          <span className="software-status-indicator"></span>
          <span>SHAIL Active</span>
        </div>

        {/* Swipe Handle */}
        <div className="software-toolbar-swipe-handle">
          <div className="swipe-handle-icon">↓</div>
          <span className="swipe-handle-text">Swipe down to Bird View</span>
        </div>
      </div>
    </div>
  );
}

export default SoftwareToolbar;
