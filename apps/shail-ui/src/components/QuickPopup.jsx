
import { useState, useEffect } from 'react';
import UniversalMenu from './UniversalMenu';
import './QuickPopup.css';

/**
 * QuickPopup - View 1: Quick Popup Foundation
 * 
 * A glassmorphic popup that appears in the bottom-right corner.
 * Features:
 * - Glassmorphism styling (translucent blue)
 * - Greeting display
 * - Status line
 * - Input box with placeholder
 * - Mic icon for voice input
 */
function QuickPopup({ onInput, onVoiceActivate, status = 'idle' }) {
  const [isVisible, setIsVisible] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [greeting, setGreeting] = useState('Hello Reyhan');
  const [showMenu, setShowMenu] = useState(false);

  // Show popup on mount or when triggered
  useEffect(() => {
    setIsVisible(true);
  }, []);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (inputValue.trim() && onInput) {
      onInput(inputValue);
      setInputValue('');
    }
  };

  const handleVoiceClick = () => {
    if (onVoiceActivate) {
      onVoiceActivate();
    }
  };

  if (!isVisible) return null;

  // Status ring classes based on status
  const getStatusRingClass = () => {
    if (status === 'idle') return 'status-ring-idle';
    if (status === 'listening') return 'status-ring-listening';
    if (status === 'seeing' || status === 'seeing-listening') return 'status-ring-seeing';
    if (status === 'thinking') return 'status-ring-thinking';
    return 'status-ring-idle';
  };

  return (
    <div className="quick-popup">
      <div className="quick-popup-content">
        {/* Status Ring Indicator */}
        <div className={`status-ring ${getStatusRingClass()}`}>
          <div className="status-ring-inner"></div>
        </div>

        {/* Greeting */}
        <div className="quick-popup-greeting">{greeting}</div>
        
        {/* Status Line */}
        <div className="quick-popup-status">
          {status === 'idle' && 'Ready'}
          {status === 'listening' && 'Listening...'}
          {status === 'thinking' && 'Thinking...'}
          {status === 'seeing' && 'Seeing...'}
          {status === 'seeing-listening' && 'Seeing + Listening...'}
        </div>

        {/* Input Box */}
        <form onSubmit={handleSubmit} className="quick-popup-form">
          {/* "+" Menu Button */}
          <button
            type="button"
            onClick={() => setShowMenu(!showMenu)}
            className="quick-popup-add"
            aria-label="Universal menu"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </button>

          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Hinted search text"
            className="quick-popup-input"
          />
          
          {/* Mic Icon */}
          <button
            type="button"
            onClick={handleVoiceClick}
            className="quick-popup-mic"
            aria-label="Voice input"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" y1="19" x2="12" y2="23" />
              <line x1="8" y1="23" x2="16" y2="23" />
            </svg>
          </button>
        </form>
      </div>

      {/* Universal Menu */}
      {showMenu && (
        <UniversalMenu
          onClose={() => setShowMenu(false)}
          onSelect={(option) => {
            console.log('Menu option selected:', option);
            setShowMenu(false);
          }}
        />
      )}
    </div>
  );
}

export default QuickPopup;
