import { useState, useEffect, useCallback } from 'react';
import ChatInput from './components/ChatInput';
import ChatMessages from './components/ChatMessages';
import TaskList from './components/TaskList';
import PermissionModal from './components/PermissionModal';
import QuickPopup from './components/QuickPopup';
import ChatOverlay from './components/ChatOverlay';
import AgentSoftwareView from './components/AgentSoftwareView';
import BirdsEyeView from './components/BirdsEyeView';
import { useViewManager, VIEWS } from './state/viewManager';
import { checkHealth } from './services/api';

function App() {
  const { currentView, navigateTo } = useViewManager();
  const [taskAwaitingApproval, setTaskAwaitingApproval] = useState(null);
  const [healthStatus, setHealthStatus] = useState(null);
  // Messages state: array of { id, type: 'user'|'shail', text, timestamp, status?, taskId? }
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState('idle');

  useEffect(() => {
    // Check backend health on mount
    checkHealth()
      .then((status) => setHealthStatus(status))
      .catch(() => setHealthStatus({ status: 'error' }));
  }, []);

  const handleTaskSubmitted = useCallback((result) => {
    // result contains: { task_id, status, message }
    console.log('Task submitted:', result);
    
    // Add placeholder "Shail is thinking..." message
    if (result.task_id) {
      setMessages(prev => [...prev, {
        id: `shail-${result.task_id}`,
        type: 'shail',
        text: 'Shail is processing your request...',
        timestamp: new Date(),
        status: 'pending',
        taskId: result.task_id
      }]);
    }
  }, []);

  // Handler to update messages when task status changes
  const handleTaskUpdate = useCallback((task) => {
    if (!task || !task.task_id) return;

    const messageId = `shail-${task.task_id}`;

    // Determine response text based on status
    let responseText = '';
    let status = task.status;

    if (task.status === 'completed') {
      // task.result is a dict from the database, check both summary and result.summary
      const resultData = typeof task.result === 'string' ? JSON.parse(task.result) : task.result;
      responseText = resultData?.summary || task.result?.summary || 'Task completed successfully.';
      status = 'completed';
    } else if (task.status === 'failed') {
      const resultData = typeof task.result === 'string' ? JSON.parse(task.result) : task.result;
      responseText = resultData?.summary || task.result?.summary || 'Task failed. Please try again.';
      status = 'failed';
    } else if (task.status === 'awaiting_approval') {
      const toolName = task.permission_request?.tool_name || 'an action';
      responseText = `Shail needs your approval to ${toolName}. Please check the permission modal.`;
      status = 'awaiting_approval';
    } else if (task.status === 'running') {
      responseText = 'Shail is processing your request...';
      status = 'running';
    } else if (task.status === 'pending' || task.status === 'queued') {
      responseText = 'Shail is processing your request...';
      status = 'pending';
    } else {
      // Don't update if status is unknown or already handled
      return;
    }

    // Update existing message or create new one using functional update
    setMessages(prev => {
      const existingMessageIndex = prev.findIndex(m => m.id === messageId);
      
      if (existingMessageIndex >= 0) {
        // Update existing message
        return prev.map((msg, idx) => 
          idx === existingMessageIndex
            ? { ...msg, text: responseText, status, timestamp: new Date() }
            : msg
        );
      } else {
        // Message doesn't exist yet, create it
        return [...prev, {
          id: messageId,
          type: 'shail',
          text: responseText,
          timestamp: new Date(),
          status,
          taskId: task.task_id
        }];
      }
    });
  }, []);

  const handleTaskAwaitingApproval = useCallback((task) => {
    if (task && task.status === 'awaiting_approval' && !taskAwaitingApproval) {
      setTaskAwaitingApproval(task);
    }
  }, [taskAwaitingApproval]);

  const handlePermissionAction = (action) => {
    console.log(`Permission ${action}`);
    setTaskAwaitingApproval(null);
    // Task list will auto-refresh and show updated status
  };

  const handleCloseModal = () => {
    setTaskAwaitingApproval(null);
  };

  return (
    <div className="min-h-screen bg-shail-darker">
      {/* Header */}
      <header className="glass border-b border-white/10 px-6 py-4">
        <div className="flex items-center justify-between max-w-7xl mx-auto">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-shail-blue rounded-lg flex items-center justify-center">
              <span className="text-2xl font-bold text-black">S</span>
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">Shail</h1>
              <p className="text-xs text-gray-400">AI Operating System</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {healthStatus && (
              <div className="flex items-center gap-2">
                <div
                  className={`w-2 h-2 rounded-full ${
                    healthStatus.status === 'ok' ? 'bg-green-500' : 'bg-red-500'
                  }`}
                />
                <span className="text-sm text-gray-400">
                  {healthStatus.status === 'ok' ? 'Connected' : 'Disconnected'}
                </span>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-6 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left Panel - Chat */}
          <div className="space-y-6">
            <div className="glass rounded-xl p-6">
              <h2 className="text-xl font-semibold text-white mb-4">Chat with Shail</h2>
              <ChatInput 
                onTaskSubmitted={handleTaskSubmitted}
                onMessageAdd={(message) => {
                  setMessages(prev => [...prev, message]);
                }}
              />
            </div>

            {/* Chat Messages */}
            <div className="glass rounded-xl p-6">
              <h2 className="text-xl font-semibold text-white mb-4">Conversation</h2>
              <ChatMessages messages={messages} />
            </div>
          </div>

          {/* Right Panel - Task List */}
          <div className="space-y-6">
            <div className="glass rounded-xl p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-xl font-semibold text-white">Task Queue</h2>
                <span className="text-xs text-gray-400">Auto-refreshing every 2s</span>
              </div>
              <TaskList 
                onTaskAwaitingApproval={handleTaskAwaitingApproval}
                onTaskUpdate={handleTaskUpdate}
              />
            </div>
          </div>
        </div>
      </main>

      {/* Permission Modal */}
      {taskAwaitingApproval && (
        <PermissionModal
          task={taskAwaitingApproval}
          onClose={handleCloseModal}
          onAction={handlePermissionAction}
        />
      )}
    </div>
  );
}

export default App;

