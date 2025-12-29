import { useState } from 'react';
import { submitTask } from '../services/api';

export default function ChatInput({ onTaskSubmitted, onMessageAdd }) {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage = input.trim();
    setLoading(true);
    setError(null);

    // Immediately add user message to chat
    if (onMessageAdd) {
      onMessageAdd({
        id: `user-${Date.now()}-${Math.random()}`,
        type: 'user',
        text: userMessage,
        timestamp: new Date()
      });
    }

    try {
      const result = await submitTask(userMessage);
      setInput('');
      if (onTaskSubmitted) {
        onTaskSubmitted(result);
      }
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to submit task');
      console.error('Task submission error:', err);
      
      // Add error message to chat
      if (onMessageAdd) {
        onMessageAdd({
          id: `error-${Date.now()}-${Math.random()}`,
          type: 'shail',
          text: `Error: ${err.response?.data?.detail || err.message || 'Failed to submit task'}`,
          timestamp: new Date(),
          status: 'failed'
        });
      }
      
      // Auto-clear error after 5 seconds
      setTimeout(() => setError(null), 5000);
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="w-full">
      {error && (
        <div className="mb-2 p-2 bg-red-500/20 border border-red-500/50 rounded text-red-200 text-sm">
          {error}
        </div>
      )}
      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Tell Shail what to do..."
          className="flex-1 px-4 py-3 bg-black/30 border border-white/20 rounded-lg focus:outline-none focus:ring-2 focus:ring-shail-blue focus:border-transparent text-white placeholder-gray-400"
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="px-6 py-3 bg-shail-blue hover:bg-shail-blue/80 disabled:bg-gray-600 disabled:cursor-not-allowed text-black font-semibold rounded-lg transition-colors"
        >
          {loading ? 'Sending...' : 'Send'}
        </button>
      </div>
    </form>
  );
}

