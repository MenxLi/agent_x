
import os
from typing import Sequence
from datetime import datetime
from .types import JsonType

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

def to_json_object(
    obj: object, 
    try_methods: Sequence[str] = ("model_dump", "to_json", "value_json")
    ) -> JsonType:
    
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj

    for method in try_methods:
        if hasattr(obj, method):
            return getattr(obj, method)()
    
    if isinstance(obj, (list, tuple)):
        return [to_json_object(item, try_methods=try_methods) for item in obj]
    
    if isinstance(obj, dict):
        return {str(key): to_json_object(value, try_methods=try_methods) for key, value in obj.items()}

    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")