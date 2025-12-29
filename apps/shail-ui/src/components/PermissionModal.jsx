import { useState, useEffect } from 'react';
import { approveTask, denyTask } from '../services/api';

export default function PermissionModal({ task, onClose, onAction }) {
  const [loading, setLoading] = useState(false);
  const [action, setAction] = useState(null);

  // Close modal on Escape key
  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === 'Escape' && !loading && onClose) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [loading, onClose]);

  if (!task || !task.permission_request) {
    return null;
  }

  const permission = task.permission_request;

  const handleApprove = async () => {
    setLoading(true);
    setAction('approving');
    try {
      await approveTask(task.task_id);
      if (onAction) onAction('approved');
      if (onClose) onClose();
    } catch (err) {
      console.error('Approve error:', err);
      alert(err.response?.data?.detail || 'Failed to approve');
    } finally {
      setLoading(false);
      setAction(null);
    }
  };

  const handleDeny = async () => {
    setLoading(true);
    setAction('denying');
    try {
      await denyTask(task.task_id);
      if (onAction) onAction('denied');
      if (onClose) onClose();
    } catch (err) {
      console.error('Deny error:', err);
      alert(err.response?.data?.detail || 'Failed to deny');
    } finally {
      setLoading(false);
      setAction(null);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="glass-strong rounded-xl p-6 max-w-2xl w-full border border-shail-blue/30">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-2xl font-bold text-shail-blue">Permission Required</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors"
            disabled={loading}
          >
            ✕
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <span className="text-sm text-gray-400">Task ID:</span>
            <span className="ml-2 font-mono text-sm text-gray-300">#{task.task_id}</span>
          </div>

          <div>
            <span className="text-sm text-gray-400">Action Requested:</span>
            <div className="mt-1 p-3 bg-black/30 rounded border border-white/10">
              <span className="font-semibold text-shail-blue">{permission.tool_name}</span>
            </div>
          </div>

          <div>
            <span className="text-sm text-gray-400">Details:</span>
            <div className="mt-1 p-3 bg-black/30 rounded border border-white/10">
              <pre className="text-sm text-gray-200 whitespace-pre-wrap font-mono">
                {JSON.stringify(permission.tool_args, null, 2)}
              </pre>
            </div>
          </div>

          <div>
            <span className="text-sm text-gray-400">Reason:</span>
            <div className="mt-1 p-3 bg-black/30 rounded border border-white/10">
              <p className="text-sm text-gray-200">{permission.rationale}</p>
            </div>
          </div>

          <div className="flex gap-3 pt-4">
            <button
              onClick={handleApprove}
              disabled={loading}
              className="flex-1 px-6 py-3 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-colors"
            >
              {action === 'approving' ? 'Approving...' : '✓ Approve'}
            </button>
            <button
              onClick={handleDeny}
              disabled={loading}
              className="flex-1 px-6 py-3 bg-red-600 hover:bg-red-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-colors"
            >
              {action === 'denying' ? 'Denying...' : '✕ Deny'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

