

import os
import platform
from datetime import datetime
from ..toolbox import ToolBox

def _read_text_if_exists(path: str) -> str:
    try:
        with open(path, "rt", encoding="utf-8", errors="ignore") as handle:
            return handle.read()
    except OSError:
        return ""


def _parse_bool_env(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None:
        return None

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None

def _is_in_container() -> bool:
    """
    Best-effort detection for common container runtimes.

    This remains heuristic. Callers that need a source of truth should use an
    explicit environment variable override.
    """
    forced = _parse_bool_env("AGENTX_IN_CONTAINER")
    if forced is not None:
        return forced

    runtime_hint = _parse_bool_env("container")
    if runtime_hint is not None:
        return runtime_hint

    marker_paths = (
        "/.dockerenv",
        "/.containerenv",
        "/run/.containerenv",
        "/run/systemd/container",
    )
    if any(os.path.exists(path) for path in marker_paths):
        return True

    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        return True

    proc_indicators = (
        "docker",
        "containerd",
        "kubepods",
        "podman",
        "libpod",
        "lxc",
    )
    for proc_file in (
        "/proc/1/cgroup",
        "/proc/self/cgroup",
        "/proc/1/mountinfo",
        "/proc/self/mountinfo",
    ):
        content = _read_text_if_exists(proc_file).lower()
        if any(indicator in content for indicator in proc_indicators):
            return True

    return False

def system_info() -> dict:
    """
    Get basic system information
    """
    info = {
        "is_docker_container": _is_in_container(),
        "os": platform.system(),
        "os_version": platform.version(),
        "node_name": platform.node(),
        "release": platform.release(),
        "architecture": platform.machine(),
        "Processor": platform.processor(),
    }
    return info

def system_time() -> str:
    """
    Get the current system time and timezone
    """
    now = datetime.now().astimezone()
    return now.isoformat()

def register_system_tools(toolbox: ToolBox):
    toolbox.register(system_info)
    toolbox.register(system_time)