
import os
from .types import JsonType
from datetime import datetime

def fmt_size(size: int | float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.2f}{unit}"
        size /= 1024
    return f"{size:.2f}PB"

def fmt_time(timestamp: float) -> str:
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def parse_bool(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None:
        return None

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None

def to_json_object(obj: object) -> JsonType:
    
    if hasattr(obj, "model_dump"):  # Pydantic model
        return getattr(obj, "model_dump")()
    if hasattr(obj, "to_json"):     # ErrorInfo class
        return getattr(obj, "to_json")()
    if hasattr(obj, "value_json"):  # Result class
        return getattr(obj, "value_json")()
    
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    
    if isinstance(obj, (list, tuple)):
        return [to_json_object(item) for item in obj]
    
    if isinstance(obj, dict):
        return {str(key): to_json_object(value) for key, value in obj.items()}

    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")