import { useState, useRef, useEffect } from 'react';
import './UniversalMenu.css';

/**
 * UniversalMenu - Universal "+" Menu
 * 
 * Provides options for:
 * - Upload files
 * - Import from Google Drive (stub)
 * - Import from Apple Files (stub)
 * - Import GitHub repo (stub)
 * - Import CAD/Simulink files
 */
function UniversalMenu({ onClose, onSelect }) {
  const [isOpen, setIsOpen] = useState(true);
  const menuRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setIsOpen(false);
        if (onClose) onClose();
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen, onClose]);

  const handleSelect = (option) => {
    if (onSelect) {
      onSelect(option);
    }
    setIsOpen(false);
    if (onClose) onClose();
  };

  if (!isOpen) return null;

  const menuOptions = [
    { id: 'upload', label: 'Upload files', icon: '📁' },
    { id: 'google_drive', label: 'Import from Google Drive', icon: '☁️', stub: true },
    { id: 'apple_files', label: 'Import from Apple Files', icon: '📂', stub: true },
    { id: 'github', label: 'Import GitHub repo', icon: '🔗', stub: true },
    { id: 'cad', label: 'Import CAD/Simulink files', icon: '⚙️' },
  ];

  return (
    <div className="universal-menu" ref={menuRef}>
      <div className="universal-menu-content">
        {menuOptions.map((option) => (
          <button
            key={option.id}
            className={`universal-menu-item ${option.stub ? 'stub' : ''}`}
            onClick={() => handleSelect(option.id)}
          >
            <span className="universal-menu-icon">{option.icon}</span>
            <span className="universal-menu-label">{option.label}</span>
            {option.stub && <span className="universal-menu-stub">(stub)</span>}
          </button>
        ))}
      </div>
    </div>
  );
}

export default UniversalMenu;
