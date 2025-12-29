import { useState, useEffect, useRef } from 'react';
import './ChatOverlay.css';

/**
 * ChatOverlay - View 2: Chat Overlay
 * 
 * Features:
 * - Right-side panel design
 * - Chat bubbles (LLM + user)
 * - Expand/collapse functionality
 * - Inline images support
 * - Inline CAD preview support
 * - Code blocks support
 * - Threaded responses
 * - Input bar + "+" menu
 */
function ChatOverlay({ isOpen, onClose, messages = [] }) {
  const [isExpanded, setIsExpanded] = useState(true);
  const [inputValue, setInputValue] = useState('');
  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  if (!isOpen) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    if (inputValue.trim()) {
      // Handle message submission
      setInputValue('');
    }
  };

  return (
    <div className={`chat-overlay ${isExpanded ? 'expanded' : 'collapsed'}`}>
      <div className="chat-overlay-header">
        <h3>Chat with SHAIL</h3>
        <div className="chat-overlay-controls">
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="chat-overlay-toggle"
            aria-label={isExpanded ? 'Collapse' : 'Expand'}
          >
            {isExpanded ? '−' : '+'}
          </button>
          <button
            onClick={onClose}
            className="chat-overlay-close"
            aria-label="Close"
          >
            ×
          </button>
        </div>
      </div>

      {isExpanded && (
        <>
          <div className="chat-overlay-messages">
            {messages.length === 0 ? (
              <div className="chat-overlay-empty">
                Start a conversation with SHAIL...
              </div>
            ) : (
              messages.map((msg, idx) => (
                <div
                  key={idx}
                  className={`chat-message chat-message-${msg.type}`}
                >
                  <div className="chat-message-content">
                    {msg.text}
                    {msg.code && (
                      <pre className="chat-message-code">
                        <code>{msg.code}</code>
                      </pre>
                    )}
                    {msg.image && (
                      <img src={msg.image} alt="Chat image" className="chat-message-image" />
                    )}
                  </div>
                  <div className="chat-message-time">
                    {new Date(msg.timestamp).toLocaleTimeString()}
                  </div>
                </div>
              ))
            )}
            <div ref={messagesEndRef} />
          </div>

          <form onSubmit={handleSubmit} className="chat-overlay-input">
            <button type="button" className="chat-overlay-add">+</button>
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="Type your message..."
              className="chat-overlay-input-field"
            />
            <button type="submit" className="chat-overlay-send">Send</button>
          </form>
        </>
      )}
    </div>
  );
}

export default ChatOverlay;
