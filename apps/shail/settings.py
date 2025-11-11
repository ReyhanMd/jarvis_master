import os
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
else:
    # Try loading from current directory as fallback
    load_dotenv()


class Settings(BaseModel):
    # Feature flags
    use_gemini: bool = Field(default=True)
    use_whisper_local: bool = Field(default=True)

    # API Keys / Models
    gemini_api_key: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = Field(default=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"))

    # Paths
    workspace_root: str = Field(default=os.getenv("SHAIL_WORKSPACE_ROOT", os.getcwd()))
    audit_log_path: str = Field(default=os.getenv("SHAIL_AUDIT_LOG", os.path.join(os.getcwd(), "shail_audit.jsonl")))

    # Memory / DB
    sqlite_path: str = Field(default=os.getenv("SHAIL_SQLITE", os.path.join(os.getcwd(), "shail_memory.sqlite3")))

    # Redis / Queue
    redis_url: str = Field(default=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    task_queue_name: str = Field(default=os.getenv("SHAIL_TASK_QUEUE", "shail_tasks"))


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


