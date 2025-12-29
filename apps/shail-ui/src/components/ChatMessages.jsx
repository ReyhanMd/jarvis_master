import { useEffect, useRef } from 'react';

/**
 * ChatMessages Component
 * 
 * Displays conversation history in a chat bubble format.
 * - User messages: Right-aligned, blue background
 * - Shail messages: Left-aligned, dark background
 * - Status indicators for task progress
 * - Auto-scrolls to bottom when new messages arrive
 */
export default function ChatMessages({ messages = [] }) {
  const messagesEndRef = useRef(null);
  const containerRef = useRef(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  const formatTime = (timestamp) => {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffSecs = Math.floor(diffMs / 1000);
    const diffMins = Math.floor(diffSecs / 60);

    if (diffSecs < 10) return 'just now';
    if (diffSecs < 60) return `${diffSecs} seconds ago`;
    if (diffMins < 60) return `${diffMins} minute${diffMins > 1 ? 's' : ''} ago`;
    
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const getStatusIndicator = (status) => {
    if (!status) return null;

    switch (status) {
      case 'pending':
      case 'running':
        return (
          <div className="flex items-center gap-1 text-xs text-gray-400">
            <div className="w-2 h-2 border-2 border-shail-blue border-t-transparent rounded-full animate-spin"></div>
            <span>Processing...</span>
          </div>
        );
      case 'completed':
        return (
          <div className="flex items-center gap-1 text-xs text-green-400">
            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
            </svg>
            <span>Completed</span>
          </div>
        );
      case 'failed':
        return (
          <div className="flex items-center gap-1 text-xs text-red-400">
            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
            </svg>
            <span>Failed</span>
          </div>
        );
      case 'awaiting_approval':
        return (
          <div className="flex items-center gap-1 text-xs text-yellow-400">
            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
            </svg>
            <span>Awaiting approval</span>
          </div>
        );
      default:
        return null;
    }
  };

  if (messages.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        <div className="text-center">
          <p className="text-lg mb-2">No messages yet</p>
          <p className="text-sm">Start a conversation with Shail</p>
        </div>
      </div>
    );
  }

  return (
    <div 
      ref={containerRef}
      className="flex flex-col gap-3 h-96 overflow-y-auto px-1"
      style={{ scrollBehavior: 'smooth' }}
    >
      {messages.map((message) => {
        const isUser = message.type === 'user';
        const timestamp = formatTime(message.timestamp);
        const statusIndicator = getStatusIndicator(message.status);

        return (
          <div
            key={message.id}
            className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[80%] rounded-lg px-4 py-2 ${
                isUser
                  ? 'bg-shail-blue text-black'
                  : 'bg-black/40 text-white border border-white/10'
              }`}
            >
              {/* Message text */}
              <p className="text-sm whitespace-pre-wrap break-words">
                {message.text}
              </p>

              {/* Status indicator and timestamp */}
              <div className="flex items-center justify-between gap-2 mt-2">
                {!isUser && statusIndicator && (
                  <div>{statusIndicator}</div>
                )}
                {timestamp && (
                  <span
                    className={`text-xs ${
                      isUser ? 'text-black/70' : 'text-gray-400'
                    }`}
                  >
                    {timestamp}
                  </span>
                )}
              </div>
            </div>
          </div>
        );
      })}
      <div ref={messagesEndRef} />
    </div>
  );
}

