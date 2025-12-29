"""File parsers for different file types."""

import logging
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_cad_file(file_path: str) -> Dict[str, Any]:
    """Parse CAD files (FCStd, SLDPRT, etc.)."""
    path = Path(file_path)
    return {
        "type": "cad",
        "file_path": str(path),
        "extension": path.suffix.lower(),
        "size": path.stat().st_size if path.exists() else 0,
        "note": "Full CAD parsing requires specific CAD library",
    }


def parse_image_file(file_path: str) -> Dict[str, Any]:
    """Parse image files."""
    path = Path(file_path)
    try:
        from PIL import Image
        img = Image.open(file_path)
        return {
            "type": "image",
            "file_path": str(path),
            "format": img.format,
            "size": img.size,
            "mode": img.mode,
        }
    except ImportError:
        return {
            "type": "image",
            "file_path": str(path),
            "note": "PIL/Pillow not installed",
        }


def parse_document_file(file_path: str) -> Dict[str, Any]:
    """Parse document files (PDF, DOCX, etc.)."""
    path = Path(file_path)
    return {
        "type": "document",
        "file_path": str(path),
        "extension": path.suffix.lower(),
        "size": path.stat().st_size if path.exists() else 0,
        "note": "Full document parsing requires specific libraries",
    }


def parse_code_file(file_path: str) -> Dict[str, Any]:
    """Parse code files."""
    path = Path(file_path)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return {
            "type": "code",
            "file_path": str(path),
            "extension": path.suffix.lower(),
            "lines": len(content.splitlines()),
            "size": len(content),
            "language": _detect_language(path.suffix),
        }
    except Exception as e:
        return {
            "type": "code",
            "file_path": str(path),
            "error": str(e),
        }


def _detect_language(extension: str) -> str:
    """Detect programming language from file extension."""
    lang_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".jsx": "javascript",
        ".tsx": "typescript",
        ".java": "java",
        ".cpp": "cpp",
        ".c": "c",
        ".rs": "rust",
        ".go": "go",
        ".rb": "ruby",
        ".php": "php",
    }
    return lang_map.get(extension.lower(), "unknown")


def parse_file(file_path: str) -> Dict[str, Any]:
    """
    Parse a file based on its type.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Dictionary with parsed file information
    """
    path = Path(file_path)
    extension = path.suffix.lower()
    
    # CAD files
    if extension in [".fcstd", ".sldprt", ".sldasm", ".step", ".stp", ".iges", ".igs"]:
        return parse_cad_file(file_path)
    
    # Image files
    elif extension in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp"]:
        return parse_image_file(file_path)
    
    # Document files
    elif extension in [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"]:
        return parse_document_file(file_path)
    
    # Code files
    elif extension in [".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cpp", ".c", ".rs", ".go", ".rb", ".php"]:
        return parse_code_file(file_path)
    
    # Default
    else:
        return {
            "type": "unknown",
            "file_path": str(path),
            "extension": extension,
            "size": path.stat().st_size if path.exists() else 0,
        }
