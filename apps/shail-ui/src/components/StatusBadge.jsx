export default function StatusBadge({ status }) {
  const statusConfig = {
    pending: { label: 'Pending', color: 'bg-gray-500', text: 'text-gray-200' },
    running: { label: 'Running', color: 'bg-blue-500', text: 'text-blue-100' },
    awaiting_approval: { label: 'Awaiting Approval', color: 'bg-yellow-500', text: 'text-yellow-100' },
    completed: { label: 'Completed', color: 'bg-green-500', text: 'text-green-100' },
    failed: { label: 'Failed', color: 'bg-red-500', text: 'text-red-100' },
    denied: { label: 'Denied', color: 'bg-red-600', text: 'text-red-100' },
  };

  const config = statusConfig[status] || statusConfig.pending;

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${config.color} ${config.text}`}>
      {config.label}
    </span>
  );
}

