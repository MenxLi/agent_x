from .entrypoint import setup_agent, interactive_session, main
from .display import DisplayAbstract, Display, NullDisplay
from .types import Result, ToolResultType, ErrorInfo
from .command import Command, CommandRegistry
from .toolbox import ToolBox, ToolCallContext
from .toolcall import tool_attr
from .agent import Agent

def __warn_auto_confirm():
    from .config import app_config
    import rich, rich.panel
    if app_config().auto_confirm:
        rich.print(
            rich.panel.Panel(
                "[bold yellow]Auto-confirm is enabled.[/bold yellow]\nPlease be cautious as the agent may execute actions without confirmation, including potentially harmful commands if misused.\nIt's recommended to keep this setting disabled unless you have a specific use case that requires it.",
                title="[bold red]Warning[/bold red]", border_style="red"
                ),
        )
__warn_auto_confirm()

__all__ = [
    "Agent",
    "tool_attr",
    "ToolBox", "ToolCallContext", 
    "DisplayAbstract", "Display", "NullDisplay",
    "Command", "CommandRegistry",
    "setup_agent", "interactive_session", "main",
    "Result", "ToolResultType", "ErrorInfo",
]