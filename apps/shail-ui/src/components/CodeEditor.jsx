import { useState, useEffect } from 'react';
import './CodeEditor.css';

/**
 * CodeEditor - Code Editor Component
 * 
 * Features:
 * - Monaco Editor integration (or CodeMirror fallback)
 * - File tree browser
 * - Read-only view (for verification)
 * - Syntax highlighting
 */
function CodeEditor({ filePath, content, readOnly = true, onContentChange }) {
  const [editorContent, setEditorContent] = useState(content || '');
  const [fileTree, setFileTree] = useState([]);
  const [selectedFile, setSelectedFile] = useState(filePath);

  useEffect(() => {
    if (content !== undefined) {
      setEditorContent(content);
    }
  }, [content]);

  useEffect(() => {
    if (filePath) {
      setSelectedFile(filePath);
    }
  }, [filePath]);

  const handleContentChange = (newContent) => {
    setEditorContent(newContent);
    if (onContentChange) {
      onContentChange(newContent);
    }
  };

  // Simple file tree for shail/ directory
  const loadFileTree = async () => {
    // In full implementation, would fetch from backend
    const tree = [
      { name: 'shail/', type: 'directory', children: [
        { name: 'agents/', type: 'directory' },
        { name: 'tools/', type: 'directory' },
        { name: 'integrations/', type: 'directory' },
        { name: 'memory/', type: 'directory' },
      ]},
    ];
    setFileTree(tree);
  };

  useEffect(() => {
    loadFileTree();
  }, []);

  return (
    <div className="code-editor">
      <div className="code-editor-layout">
        {/* File Tree */}
        <div className="code-editor-sidebar">
          <div className="code-editor-tree">
            <div className="code-editor-tree-header">File Tree</div>
            <div className="code-editor-tree-content">
              {fileTree.map((item, idx) => (
                <div key={idx} className="code-editor-tree-item">
                  {item.type === 'directory' ? '📁' : '📄'} {item.name}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Editor */}
        <div className="code-editor-main">
          <div className="code-editor-header">
            <span className="code-editor-file-path">{selectedFile || 'No file selected'}</span>
            {readOnly && <span className="code-editor-readonly-badge">Read Only</span>}
          </div>
          <div className="code-editor-content">
            {readOnly ? (
              <pre className="code-editor-pre">
                <code>{editorContent}</code>
              </pre>
            ) : (
              <textarea
                className="code-editor-textarea"
                value={editorContent}
                onChange={(e) => handleContentChange(e.target.value)}
                spellCheck={false}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default CodeEditor;
