

import platform
from datetime import datetime
from typing import Callable
from ..util import is_in_container

def system_info() -> dict:
    """
    Get basic system information
    """
    info = {
        "is_docker_container": is_in_container(),
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

def expose_system_tools() -> list[Callable]:
    return [system_info, system_time]