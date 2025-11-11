import json
import os
from datetime import datetime


def write_audit(event: dict, audit_log_path: str = None) -> str:
    """Write audit event to JSONL log file."""
    if audit_log_path is None:
        # Default fallback path
        audit_log_path = os.path.join(os.getcwd(), "shail_audit.jsonl")
        audit_log_path = os.getenv("SHAIL_AUDIT_LOG", audit_log_path)
    
    os.makedirs(os.path.dirname(audit_log_path) if os.path.dirname(audit_log_path) else ".", exist_ok=True)
    record = {"ts": datetime.utcnow().isoformat() + "Z", **event}
    with open(audit_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return audit_log_path


