import { useState } from 'react';
import CodeEditor from './CodeEditor';
import './SelfModApprovalModal.css';

/**
 * SelfModApprovalModal - Approval Modal with Diff
 * 
 * Features:
 * - Diff viewer (react-diff-viewer or simple diff)
 * - Approve/Reject workflow
 * - Rationale display
 * - Protected file warnings
 */
function SelfModApprovalModal({ 
  isOpen, 
  onClose, 
  onApprove, 
  onReject,
  modification 
}) {
  const [viewMode, setViewMode] = useState('diff'); // 'diff', 'old', 'new'

  if (!isOpen || !modification) return null;

  const { file_path, diff, rationale, is_protected, backup_path } = modification;

  const handleApprove = () => {
    if (onApprove) {
      onApprove(modification);
    }
    onClose();
  };

  const handleReject = () => {
    if (onReject) {
      onReject(modification);
    }
    onClose();
  };

  return (
    <div className="self-mod-modal-overlay" onClick={onClose}>
      <div className="self-mod-modal" onClick={(e) => e.stopPropagation()}>
        <div className="self-mod-modal-header">
          <h2>Self-Modification Approval</h2>
          <button className="self-mod-modal-close" onClick={onClose}>×</button>
        </div>

        <div className="self-mod-modal-content">
          {/* File Info */}
          <div className="self-mod-modal-info">
            <div className="self-mod-modal-file-path">
              <strong>File:</strong> {file_path}
            </div>
            {is_protected && (
              <div className="self-mod-modal-warning">
                ⚠️ This is a protected file and requires explicit approval
              </div>
            )}
            {backup_path && (
              <div className="self-mod-modal-backup">
                <strong>Backup:</strong> {backup_path}
              </div>
            )}
          </div>

          {/* Rationale */}
          {rationale && (
            <div className="self-mod-modal-rationale">
              <strong>Rationale:</strong>
              <p>{rationale}</p>
            </div>
          )}

          {/* View Mode Toggle */}
          <div className="self-mod-modal-view-toggle">
            <button
              className={viewMode === 'diff' ? 'active' : ''}
              onClick={() => setViewMode('diff')}
            >
              Diff
            </button>
            <button
              className={viewMode === 'old' ? 'active' : ''}
              onClick={() => setViewMode('old')}
            >
              Old
            </button>
            <button
              className={viewMode === 'new' ? 'active' : ''}
              onClick={() => setViewMode('new')}
            >
              New
            </button>
          </div>

          {/* Diff/Code View */}
          <div className="self-mod-modal-editor">
            {viewMode === 'diff' && diff && (
              <div className="self-mod-modal-diff">
                <pre className="diff-content">{diff.diff || 'No diff available'}</pre>
              </div>
            )}
            {viewMode === 'old' && (
              <CodeEditor
                filePath={file_path}
                content={diff?.old_content || ''}
                readOnly={true}
              />
            )}
            {viewMode === 'new' && (
              <CodeEditor
                filePath={file_path}
                content={diff?.new_content || ''}
                readOnly={true}
              />
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="self-mod-modal-actions">
          <button
            className="self-mod-modal-reject"
            onClick={handleReject}
          >
            Reject
          </button>
          <button
            className="self-mod-modal-approve"
            onClick={handleApprove}
          >
            Approve
          </button>
        </div>
      </div>
    </div>
  );
}

export default SelfModApprovalModal;
