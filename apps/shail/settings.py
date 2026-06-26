import os
from typing import List, Optional
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv

_project_root = Path(__file__).parent.parent.parent
_env_path = _project_root / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
    _env_source = str(_env_path)
else:
    load_dotenv()
    _env_source = "cwd"


class Settings(BaseModel):
    # Local LLM (Ollama)
    ollama_base_url: str = Field(default=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    # Sprint 6 (ADR-006): switched default from gemma4:e4b (9.6 GB, multimodal)
    # to gemma3:4b Q4_K_M (~2.6 GB, text-only). Lazy-load llava for Ghost
    # Cursor vision separately. Idle footprint drops 7 GB.
    ollama_chat_model: str = Field(default=os.getenv("OLLAMA_CHAT_MODEL", "gemma3:4b-it-q4_K_M"))
    ollama_vision_model: str = Field(default=os.getenv("OLLAMA_VISION_MODEL", "llava:7b"))
    ollama_embed_model: str = Field(default=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"))
    ollama_embed_dim: int = Field(default=int(os.getenv("OLLAMA_EMBED_DIM", "768")))
    # Heat / RAM tuning (per-request overrides; see call_gemma)
    # Gemma3:4b supports up to 128K, but 8192 gives a comfortable headroom for
    # the context packet (~3700 chars) + past chats + MCP + 4-6 history turns,
    # without paying the VRAM cost of the full window.
    ollama_num_ctx: int       = Field(default=int(os.getenv("OLLAMA_NUM_CTX", "8192")))
    ollama_num_thread: int    = Field(default=int(os.getenv("OLLAMA_NUM_THREAD", "4")))
    ollama_keep_alive: str    = Field(default=os.getenv("OLLAMA_KEEP_ALIVE", "5m"))

    # Paths
    workspace_root: str = Field(default=os.getenv("SHAIL_WORKSPACE_ROOT", os.getcwd()))
    audit_log_path: str = Field(default=os.getenv("SHAIL_AUDIT_LOG", os.path.join(os.getcwd(), "shail_audit.jsonl")))

    # Memory / DB
    sqlite_path: str = Field(default=os.getenv("SHAIL_SQLITE", os.path.expanduser("~/Library/Application Support/SHAIL/metadata.db")))
    rag_vector_store: str = Field(default=os.getenv("RAG_VECTOR_STORE", "chroma"))
    rag_pg_dsn: str = Field(default=os.getenv("RAG_PG_DSN", "postgresql://postgres:postgres@localhost:5432/shail_rag"))
    rag_chroma_path: str = Field(default=os.getenv(
        "RAG_CHROMA_PATH",
        os.path.expanduser("~/Library/Application Support/SHAIL/memory/chroma"),
    ))
    rag_default_top_k: int = Field(default=int(os.getenv("RAG_TOP_K", "5")))
    rag_chunk_size: int = Field(default=int(os.getenv("RAG_CHUNK_SIZE", "800")))
    rag_chunk_overlap: int = Field(default=int(os.getenv("RAG_CHUNK_OVERLAP", "120")))
    rag_embedding_dim: int = Field(default=int(os.getenv("RAG_EMBEDDING_DIM", "768")))
    capture_artifact_dir: str = Field(default=os.getenv(
        "SHAIL_CAPTURE_ARTIFACT_DIR",
        os.path.expanduser("~/Library/Application Support/SHAIL/capture_artifacts"),
    ))

    # macOS memory tiers
    macos_memory_root: str = Field(default=os.getenv(
        "SHAIL_MEMORY_ROOT",
        os.path.expanduser("~/Library/Application Support/SHAIL/memory"),
    ))
    path_index_db: str = Field(default=os.getenv(
        "SHAIL_PATH_INDEX_DB",
        os.path.expanduser("~/Library/Application Support/SHAIL/memory/path_index.db"),
    ))
    # Colon-separated list of extra roots to scan at startup (in addition to
    # the auto-discovered defaults and any roots persisted in the DB).
    # Example: SHAIL_SCAN_ROOTS=/Users/reyhan/shail workspace /shail_master:/Users/reyhan/work
    scan_roots: List[str] = Field(
        default_factory=lambda: [
            p.strip() for p in os.getenv("SHAIL_SCAN_ROOTS", "").split(":")
            if p.strip()
        ]
    )
    cloud_index_db: str = Field(default=os.getenv(
        "SHAIL_CLOUD_INDEX_DB",
        os.path.expanduser("~/Library/Application Support/SHAIL/memory/cloud_index.db"),
    ))
    ephemeral_ttl_hours: int = Field(default=int(os.getenv("SHAIL_EPHEMERAL_TTL_HOURS", "24")))
    ephemeral_max_records: int = Field(default=int(os.getenv("SHAIL_EPHEMERAL_MAX_RECORDS", "5000")))

    # Redis / Queue
    redis_url: str = Field(default=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    task_queue_name: str = Field(default=os.getenv("SHAIL_TASK_QUEUE", "shail_tasks"))

    # Service URLs
    ui_twin_url: str = Field(default=os.getenv("UI_TWIN_URL", "http://localhost:8001"))
    action_executor_url: str = Field(default=os.getenv("ACTION_EXECUTOR_URL", "http://localhost:8002"))
    vision_url: str = Field(default=os.getenv("VISION_URL", "http://localhost:8003"))
    rag_url: str = Field(default=os.getenv("RAG_URL", "http://localhost:8004"))

    # JWT
    jwt_secret: str = Field(default_factory=lambda: os.getenv("SHAIL_JWT_SECRET", "changeme"))

    # Google OAuth2 — used for sign-in AND for Drive/Gmail MCP connectors.
    google_client_id:     str = Field(default=os.getenv("GOOGLE_CLIENT_ID", ""))
    google_client_secret: str = Field(default=os.getenv("GOOGLE_CLIENT_SECRET", ""))

    # GitHub OAuth (MCP)
    github_client_id:     str = Field(default=os.getenv("GITHUB_CLIENT_ID", ""))
    github_client_secret: str = Field(default=os.getenv("GITHUB_CLIENT_SECRET", ""))

    # Notion OAuth (MCP)
    notion_client_id:     str = Field(default=os.getenv("NOTION_CLIENT_ID", ""))
    notion_client_secret: str = Field(default=os.getenv("NOTION_CLIENT_SECRET", ""))

    # Public origin used to build OAuth redirect_uri values. Override in
    # production so OAuth providers can reach the callback endpoint.
    public_origin:        str = Field(default=os.getenv("SHAIL_PUBLIC_ORIGIN", "http://localhost:8000"))

    # Compatibility stubs — removed Gemini; agents that still reference these
    # will get empty strings instead of AttributeErrors.
    gemini_api_key: str = Field(default="")
    gemini_model: str   = Field(default="")

    # Retrieval-evolution feature flags. All default OFF. Land dark, flip via env.
    shail_exact_index_write:    bool = Field(default=os.getenv("SHAIL_EXACT_INDEX_WRITE", "false").lower() == "true")
    shail_hybrid_retrieval:     bool = Field(default=os.getenv("SHAIL_HYBRID_RETRIEVAL", "false").lower() == "true")
    shail_context_packet:       bool = Field(default=os.getenv("SHAIL_CONTEXT_PACKET", "false").lower() == "true")
    shail_capture_chunking:     bool = Field(default=os.getenv("SHAIL_CAPTURE_CHUNKING", "false").lower() == "true")
    shail_blueprint_versioning: bool = Field(default=os.getenv("SHAIL_BLUEPRINT_VERSIONING", "false").lower() == "true")
    shail_rerank:               bool = Field(default=os.getenv("SHAIL_RERANK", "false").lower() == "true")
    shail_retrieval_debug:      bool = Field(default=os.getenv("SHAIL_RETRIEVAL_DEBUG", "false").lower() == "true")
    # Plan Part A5: lazy-embed local files matched by query before vector RAG runs.
    shail_local_files_in_chat:  bool = Field(default=os.getenv("SHAIL_LOCAL_FILES_IN_CHAT", "true").lower() == "true")
    # Production-hardening knobs for pointer-only local-file retrieval.
    shail_local_files_k:               int   = Field(default=int(os.getenv("SHAIL_LOCAL_FILES_K", "5")))
    shail_local_files_snippet_chars:   int   = Field(default=int(os.getenv("SHAIL_LOCAL_FILES_SNIPPET_CHARS", "1500")))
    shail_local_files_read_cap_bytes:  int   = Field(default=int(os.getenv("SHAIL_LOCAL_FILES_READ_CAP_BYTES", "25000000")))
    shail_local_files_min_score:       float = Field(default=float(os.getenv("SHAIL_LOCAL_FILES_MIN_SCORE", "0.05")))
    # Plan Part B7: blueprint quality threshold for auto-redact gate (0.0–1.0).
    blueprint_quality_threshold: float = Field(default=float(os.getenv("SHAIL_BLUEPRINT_QUALITY_THRESHOLD", "0.4")))
    auto_redact_default:        bool = Field(default=os.getenv("SHAIL_AUTO_REDACT_DEFAULT", "false").lower() == "true")
    capture_artifacts_enabled:        bool = Field(default=os.getenv("SHAIL_CAPTURE_ARTIFACTS_ENABLED", "false").lower() == "true")
    capture_v2_enabled:               bool = Field(default=os.getenv("SHAIL_CAPTURE_V2_ENABLED", "false").lower() == "true")
    semantic_chunk_promotion_enabled: bool = Field(default=os.getenv("SHAIL_SEMANTIC_CHUNK_PROMOTION_ENABLED", "false").lower() == "true")
    pdf_extraction_enabled:           bool = Field(default=os.getenv("SHAIL_PDF_EXTRACTION_ENABLED", "false").lower() == "true")
    github_diff_capture_enabled:      bool = Field(default=os.getenv("SHAIL_GITHUB_DIFF_CAPTURE_ENABLED", "false").lower() == "true")
    structured_dom_capture_enabled:   bool = Field(default=os.getenv("SHAIL_STRUCTURED_DOM_CAPTURE_ENABLED", "false").lower() == "true")
    capture_bundle_version:           str = Field(default=os.getenv("SHAIL_CAPTURE_BUNDLE_VERSION", "capture-v1.0.0"))

    # ── SuperMemory Phase 1: Hybrid Local/Global Retrieval ───────────────
    supermemory_api_url:              str   = Field(default=os.getenv("SUPERMEMORY_API_URL", "https://api.supermemory.ai"))
    supermemory_api_key:              str   = Field(default=os.getenv("SUPERMEMORY_API_KEY", ""))
    supermemory_use_global:           bool  = Field(default=os.getenv("SHAIL_USE_GLOBAL_MEMORY", "false").lower() == "true")
    supermemory_fallback_threshold:   int   = Field(default=int(os.getenv("SUPERMEMORY_FALLBACK_THRESHOLD", "3")))
    supermemory_timeout_sec:          float = Field(default=float(os.getenv("SUPERMEMORY_TIMEOUT_SEC", "5.0")))
    retrieval_strategy:               str   = Field(default=os.getenv("SHAIL_RETRIEVAL_STRATEGY", "local_only"))  # local_only|global_only|hybrid

    # ── SuperMemory Phase 2: Shared RAG Cache ───────────────────────────
    cache_enabled:                    bool  = Field(default=os.getenv("SHAIL_CACHE_ENABLED", "false").lower() == "true")
    cache_backend:                    str   = Field(default=os.getenv("SHAIL_CACHE_BACKEND", "sqlite"))  # redis|sqlite|disk
    cache_ttl_sec:                    int   = Field(default=int(os.getenv("SHAIL_CACHE_TTL_SEC", "3600")))
    cache_sqlite_path:                str   = Field(default=os.getenv("SHAIL_CACHE_SQLITE_PATH", os.path.expanduser("~/Library/Application Support/SHAIL/retrieval_cache.db")))
    cache_disk_dir:                   str   = Field(default=os.getenv("SHAIL_CACHE_DISK_DIR", os.path.expanduser("~/Library/Application Support/SHAIL/cache")))

    # ── SuperMemory Phase 3: Auto-Ingest Generated Outputs ──────────────
    ingest_generated_outputs:         bool  = Field(default=os.getenv("SHAIL_AUTO_INGEST", "false").lower() == "true")
    ingest_quality_threshold:         float = Field(default=float(os.getenv("SHAIL_INGEST_QUALITY_THRESHOLD", "0.6")))
    ingest_max_queue_size:            int   = Field(default=int(os.getenv("SHAIL_INGEST_QUEUE_SIZE", "100")))
    memory_quality_score_weights:     dict  = Field(default_factory=lambda: {"has_artifacts": 0.3, "no_error": 0.4, "length": 0.3})

    # ── SuperMemory Phase 5: Cross-Agent Shared Memory ───────────────────
    enable_shared_context:            bool  = Field(default=os.getenv("SHAIL_SHARED_CONTEXT", "false").lower() == "true")
    shared_context_backend:           str   = Field(default=os.getenv("SHAIL_SHARED_CONTEXT_BACKEND", "sqlite"))  # sqlite|redis
    shared_context_ttl_hours:         int   = Field(default=int(os.getenv("SHAIL_SHARED_CONTEXT_TTL_HOURS", "24")))
    shared_context_sqlite_path:       str   = Field(default=os.getenv("SHAIL_SC_SQLITE_PATH", os.path.expanduser("~/Library/Application Support/SHAIL/shared_context.db")))

    # ── SuperMemory Phase 6: Observability + Metrics ─────────────────────
    metrics_enabled:                  bool  = Field(default=os.getenv("SHAIL_METRICS_ENABLED", "true").lower() == "true")
    trace_enabled:                    bool  = Field(default=os.getenv("SHAIL_TRACE_ENABLED", "false").lower() == "true")
    otel_endpoint:                    str   = Field(default=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""))

    # ── SuperMemory Phase 7: Hierarchical Taxonomy Engine ────────────────
    taxonomy_enabled:                 bool  = Field(default=os.getenv("SHAIL_TAXONOMY_ENABLED", "true").lower() == "true")
    taxonomy_config_path:             str   = Field(default=os.getenv("SHAIL_TAXONOMY_CONFIG", os.path.expanduser("~/.config/SHAIL/taxonomy.json")))

    # ── Sprint 2: Memory Reliability ────────────────────────────────────
    # Fusion mode: "rrf" (Reciprocal Rank Fusion, scale-independent) or "weighted" (legacy)
    fusion_mode:                      str   = Field(default=os.getenv("SHAIL_FUSION_MODE", "rrf"))
    # Semantic dedup before ingest
    semantic_dedup_enabled:           bool  = Field(default=os.getenv("SHAIL_SEMANTIC_DEDUP", "true").lower() == "true")
    semantic_dedup_window:            int   = Field(default=int(os.getenv("SHAIL_DEDUP_WINDOW", "256")))
    semantic_dedup_threshold:         float = Field(default=float(os.getenv("SHAIL_DEDUP_THRESHOLD", "0.95")))
    semantic_dedup_db:                str   = Field(default=os.getenv("SHAIL_DEDUP_DB", os.path.expanduser("~/Library/Application Support/SHAIL/dedup.db")))
    # Dead-letter queue
    dead_letter_db:                   str   = Field(default=os.getenv("SHAIL_DEAD_LETTER_DB", os.path.expanduser("~/Library/Application Support/SHAIL/dead_letter.db")))
    # Retrieval usefulness feedback
    usefulness_reranking_enabled:     bool  = Field(default=os.getenv("SHAIL_USEFULNESS_RERANK", "true").lower() == "true")
    usefulness_boost_weight:          float = Field(default=float(os.getenv("SHAIL_USEFULNESS_BOOST", "0.15")))
    usefulness_db:                    str   = Field(default=os.getenv("SHAIL_USEFULNESS_DB", os.path.expanduser("~/Library/Application Support/SHAIL/usefulness.db")))

    # ── Dynamic blueprint sizing (replaces hard-coded 14K/16K/24K caps) ────
    # context_tokens: target LLM context window in tokens. Defaults to
    # ollama_num_ctx but may be overridden when using a model with a larger
    # window than the live chat path.
    blueprint_context_tokens:         int   = Field(default=int(os.getenv("SHAIL_BLUEPRINT_CONTEXT_TOKENS", "32768")))
    blueprint_chars_per_token:        float = Field(default=float(os.getenv("SHAIL_BLUEPRINT_CHARS_PER_TOKEN", "3.5")))
    blueprint_prompt_overhead_chars:  int   = Field(default=int(os.getenv("SHAIL_BLUEPRINT_PROMPT_OVERHEAD_CHARS", "3000")))
    blueprint_response_reserve_pct:   float = Field(default=float(os.getenv("SHAIL_BLUEPRINT_RESPONSE_RESERVE_PCT", "0.25")))
    blueprint_safety_margin_pct:      float = Field(default=float(os.getenv("SHAIL_BLUEPRINT_SAFETY_MARGIN_PCT", "0.05")))
    blueprint_min_content_chars:      int   = Field(default=int(os.getenv("SHAIL_BLUEPRINT_MIN_CONTENT_CHARS", "8000")))
    blueprint_window_overlap_pct:     float = Field(default=float(os.getenv("SHAIL_BLUEPRINT_WINDOW_OVERLAP_PCT", "0.15")))
    # Hard ceiling for transcript build — defends against pathological inputs
    # (10MB sessions etc.). 0 disables the ceiling.
    blueprint_transcript_max_chars:   int   = Field(default=int(os.getenv("SHAIL_BLUEPRINT_TRANSCRIPT_MAX_CHARS", "2000000")))
    # Per-capture ingestion ceiling (raised from 50K). Set to 0 to disable.
    capture_ingest_max_chars:         int   = Field(default=int(os.getenv("SHAIL_CAPTURE_INGEST_MAX_CHARS", "2000000")))

    # ── Blueprint field caps (raised + configurable; were hard-coded 12/32/8) ──
    blueprint_max_decisions:          int   = Field(default=int(os.getenv("SHAIL_BP_MAX_DECISIONS", "64")))
    blueprint_max_qa:                 int   = Field(default=int(os.getenv("SHAIL_BP_MAX_QA", "64")))
    blueprint_max_open_questions:     int   = Field(default=int(os.getenv("SHAIL_BP_MAX_OPEN_QUESTIONS", "64")))
    blueprint_max_next_actions:       int   = Field(default=int(os.getenv("SHAIL_BP_MAX_NEXT_ACTIONS", "64")))
    blueprint_max_key_entities:       int   = Field(default=int(os.getenv("SHAIL_BP_MAX_KEY_ENTITIES", "32")))
    blueprint_max_reasoning_chains:   int   = Field(default=int(os.getenv("SHAIL_BP_MAX_REASONING_CHAINS", "32")))
    blueprint_max_failed_attempts:    int   = Field(default=int(os.getenv("SHAIL_BP_MAX_FAILED_ATTEMPTS", "32")))
    blueprint_max_facts:              int   = Field(default=int(os.getenv("SHAIL_BP_MAX_FACTS", "256")))
    blueprint_max_metrics:            int   = Field(default=int(os.getenv("SHAIL_BP_MAX_METRICS", "256")))
    blueprint_max_tables:             int   = Field(default=int(os.getenv("SHAIL_BP_MAX_TABLES", "32")))
    blueprint_max_table_rows:         int   = Field(default=int(os.getenv("SHAIL_BP_MAX_TABLE_ROWS", "512")))
    blueprint_max_code_refs:          int   = Field(default=int(os.getenv("SHAIL_BP_MAX_CODE_REFS", "64")))
    # Per-item char caps — still bounded to keep individual items sane.
    blueprint_value_cap_chars:        int   = Field(default=int(os.getenv("SHAIL_BP_VALUE_CAP_CHARS", "2000")))
    blueprint_summary_cap_chars:      int   = Field(default=int(os.getenv("SHAIL_BP_SUMMARY_CAP_CHARS", "2000")))

    # ── Capture pipeline feature toggles ───────────────────────────────────────
    capture_segments_enabled:         bool  = Field(default=os.getenv("SHAIL_CAPTURE_SEGMENTS_ENABLED", "true").lower() == "true")
    pipeline_status_enabled:          bool  = Field(default=os.getenv("SHAIL_PIPELINE_STATUS_ENABLED", "true").lower() == "true")

    # ── Single-User Mode ────────────────────────────────────────────────────────
    # The one canonical account. All auth guards enforce this identity.
    canonical_user_id:    str  = Field(default=os.getenv("SHAIL_CANONICAL_USER_ID", ""))
    canonical_user_email: str  = Field(default=os.getenv("SHAIL_CANONICAL_EMAIL", ""))
    # When false, POST /auth/register returns 403.
    allow_registration:   bool = Field(default=os.getenv("SHAIL_ALLOW_REGISTRATION", "false").lower() == "true")


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
