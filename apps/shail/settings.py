import os
from typing import List, Optional
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load .env file from project root (if it exists)
# This allows users to configure API keys and settings via .env file
# instead of manually exporting environment variables
# settings.py is at: apps/shail/settings.py
# So project root is: .parent (shail) -> .parent (apps) -> .parent (project root)
_project_root = Path(__file__).parent.parent.parent
_env_path = _project_root / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
    _env_source = str(_env_path)
else:
    # Try loading from current directory as fallback
    load_dotenv()
    _env_source = "cwd"


class Settings(BaseModel):
    # Feature flags
    use_gemini: bool = Field(default=True)
    use_whisper_local: bool = Field(default=True)

    # API Keys / Models
    gemini_api_key: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = Field(default=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"))
    rag_embedding_model: str = Field(default=os.getenv("RAG_EMBEDDING_MODEL", "text-embedding-004"))
    rag_embedding_dim: int = Field(default=int(os.getenv("RAG_EMBEDDING_DIM", "768")))
    
    # Kimi-K2 Master LLM
    kimi_k2_api_key: str = Field(default_factory=lambda: os.getenv("KIMI_K2_API_KEY", ""))
    kimi_k2_model: str = Field(default=os.getenv("KIMI_K2_MODEL", "moonshot-v1-8k"))
    use_kimi_k2_master: bool = Field(default=os.getenv("USE_KIMI_K2_MASTER", "false").lower() == "true")
    
    # ChatGPT/OpenAI Worker LLM
    openai_api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_model: str = Field(default=os.getenv("OPENAI_MODEL", "gpt-4o"))
    use_chatgpt_worker: bool = Field(default=os.getenv("USE_CHATGPT_WORKER", "false").lower() == "true")
    
    # LangGraph Studio
    langgraph_studio_url: str = Field(default=os.getenv("LANGGRAPH_STUDIO_URL", "http://localhost:8123"))
    langgraph_cloud_api_key: str = Field(default_factory=lambda: os.getenv("LANGGRAPH_CLOUD_API_KEY", ""))
    langgraph_cloud_url: str = Field(default=os.getenv("LANGGRAPH_CLOUD_URL", "https://api.langchain.com"))
    use_langgraph_cloud: bool = Field(default=os.getenv("USE_LANGGRAPH_CLOUD", "false").lower() == "true")

    # Paths
    workspace_root: str = Field(default=os.getenv("SHAIL_WORKSPACE_ROOT", os.getcwd()))
    audit_log_path: str = Field(default=os.getenv("SHAIL_AUDIT_LOG", os.path.join(os.getcwd(), "shail_audit.jsonl")))

    # Memory / DB
    sqlite_path: str = Field(default=os.getenv("SHAIL_SQLITE", os.path.join(os.getcwd(), "shail_memory.sqlite3")))
    rag_vector_store: str = Field(default=os.getenv("RAG_VECTOR_STORE", "pgvector"))  # pgvector|chroma
    rag_pg_dsn: str = Field(default=os.getenv("RAG_PG_DSN", "postgresql://postgres:postgres@localhost:5432/shail_rag"))
    rag_chroma_path: str = Field(default=os.getenv("RAG_CHROMA_PATH", os.path.join(os.getcwd(), "rag_chroma")))
    rag_default_top_k: int = Field(default=int(os.getenv("RAG_TOP_K", "5")))
    rag_chunk_size: int = Field(default=int(os.getenv("RAG_CHUNK_SIZE", "800")))
    rag_chunk_overlap: int = Field(default=int(os.getenv("RAG_CHUNK_OVERLAP", "120")))

    # Redis / Queue
    redis_url: str = Field(default=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    task_queue_name: str = Field(default=os.getenv("SHAIL_TASK_QUEUE", "shail_tasks"))
    
    # Service URLs (for LangGraph integration)
    ui_twin_url: str = Field(default=os.getenv("UI_TWIN_URL", "http://localhost:8001"))
    action_executor_url: str = Field(default=os.getenv("ACTION_EXECUTOR_URL", "http://localhost:8002"))
    vision_url: str = Field(default=os.getenv("VISION_URL", "http://localhost:8003"))
    rag_url: str = Field(default=os.getenv("RAG_URL", "http://localhost:8004"))


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        if not _settings.gemini_api_key:
            print(
                f"[Settings] Warning: GEMINI_API_KEY is missing. "
                f"Loaded .env from {_env_source}."
            )
        if not _settings.openai_api_key and _settings.use_chatgpt_worker:
            print(
                f"[Settings] Warning: OPENAI_API_KEY is missing. "
                f"Loaded .env from {_env_source}."
            )
        if not _settings.kimi_k2_api_key and _settings.use_kimi_k2_master:
            print(
                f"[Settings] Warning: KIMI_K2_API_KEY is missing. "
                f"Loaded .env from {_env_source}."
            )
    return _settings


