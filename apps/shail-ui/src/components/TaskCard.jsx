import { useState } from 'react';
import StatusBadge from './StatusBadge';

export default function TaskCard({ task, onExpand }) {
  const [expanded, setExpanded] = useState(false);

  const toggleExpand = () => {
    setExpanded(!expanded);
    if (onExpand) onExpand(task.task_id, !expanded);
  };

  const formatTime = (timestamp) => {
    if (!timestamp) return 'N/A';
    const date = new Date(timestamp);
    return date.toLocaleTimeString();
  };

  const requestText = task.request_text || task.request?.text || 'No description';
  const agent = task.result?.agent || 'Unknown';
  const summary = task.result?.summary || task.status;

  return (
    <div className="glass rounded-lg p-4 hover:bg-black/30 transition-colors cursor-pointer" onClick={toggleExpand}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-mono text-gray-400">#{task.task_id}</span>
            <StatusBadge status={task.status} />
            {agent && (
              <span className="text-xs px-2 py-0.5 bg-shail-blue/20 text-shail-blue rounded">
                {agent}
              </span>
            )}
          </div>
          <p className={`text-sm text-gray-200 mb-1 ${expanded ? '' : 'line-clamp-2'}`}>{requestText}</p>
          <span className="text-xs text-gray-500">{formatTime(task.created_at)}</span>
        </div>
      </div>

      {expanded && (
        <div className="mt-4 pt-4 border-t border-white/10 space-y-2">
          <div>
            <span className="text-xs text-gray-400">Summary:</span>
            <p className="text-sm text-gray-200 mt-1">{summary}</p>
          </div>
          {task.result?.artifacts && task.result.artifacts.length > 0 && (
            <div>
              <span className="text-xs text-gray-400">Artifacts:</span>
              <ul className="text-sm text-gray-300 mt-1 list-disc list-inside">
                {task.result.artifacts.map((artifact, idx) => (
                  <li key={idx}>{artifact.path || artifact.kind}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="text-xs text-gray-500">
            Created: {new Date(task.created_at).toLocaleString()}
            {task.updated_at !== task.created_at && (
              <> • Updated: {new Date(task.updated_at).toLocaleString()}</>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

