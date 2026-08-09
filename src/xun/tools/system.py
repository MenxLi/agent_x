

import platform
from datetime import datetime
from typing import Callable
from ..config import app_config
from ..toolcall import tool_attr, ToolCallContext

def system_info() -> dict:
    """
    Get basic system information
    """
    info = {
        "os": platform.system(),
        "os_version": platform.version(),
        "node_name": platform.node(),
        "release": platform.release(),
        "architecture": platform.machine(),
        "Processor": platform.processor(),
    }
    return info

@tool_attr(name="datetime")
def system_time() -> str:
    """ Get the current system time and timezone """
    now = datetime.now().astimezone()
    return now.isoformat()

@tool_attr(name="ask_preference")
def system_ask_user_preference(
    ctx: ToolCallContext,
    message: str, 
    choices: list[str],
    allow_extra: bool = False,
    default_choice: str | None = None,
    title: str = "User Preference Query",
    ) -> str:
    """
    Query user about their preferences. 
    Use this tool to ask the user to choose from a list of options, and return the selected option.

    - `message`: The message to display to the user explaining the context of the query.
    - `choices`: A list of strings representing the available choices for the user to select from.
    - `allow_extra`: if set to True, the user can have the option to enter their own choice if none of the provided choices are suitable.
    """
    if default_choice is not None and default_choice not in choices:
        raise ValueError(f"Default choice '{default_choice}' is not in the list of available choices.")
    return ctx.agent.display.get_choice(
        prompt="Please select your preference",
        choices=choices,
        message=message,
        title=title,
        subtitle="Agent Preference Query",
        default=default_choice,
        allow_extra=allow_extra
    )


def expose_system_tools() -> list[Callable]:
    if app_config().auto_confirm:
        return [system_info, system_time]
    else:
        return [system_info, system_time, system_ask_user_preference]