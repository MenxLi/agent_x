from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, Callable, Any
from pathlib import Path
import inspect
if TYPE_CHECKING:
    from .agent import Agent

type CommandHandlerWArgs = Callable[[Agent, Optional[str]], Any]
type CommandHandlerWOArgs = Callable[[Agent], Any]
type CommandHandler = CommandHandlerWArgs | CommandHandlerWOArgs

@dataclass
class Command:
    name: str
    description: str
    handler: CommandHandler
    _runner: Callable[[Agent, Optional[str]], None] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        n_args_accepted = len(inspect.signature(self.handler).parameters)
        if n_args_accepted == 1:
            handler = self.handler
            self._runner = lambda agent, _arguments: handler(agent)  # type: ignore[misc]
        elif n_args_accepted == 2:
            handler = self.handler
            self._runner = lambda agent, arguments: handler(agent, arguments)  # type: ignore[misc]
        else:
            raise TypeError(f"Command handler must accept 1 or 2 args, got {n_args_accepted}")
    
    @staticmethod
    def from_function(func: CommandHandler) -> Command:
        """ Create a Command from a function. """
        return Command(
            name=func.__name__,
            description=func.__doc__ or "No description provided.",
            handler=func
        )

    def invoke(self, agent: Agent, arguments: Optional[str] = None) -> None:
        self._runner(agent, arguments)

class CommandRegistry:
    def __init__(self):
        self.commands: dict[str, Command] = {}

    def register(self, *commands: Command | CommandHandler):
        for command in commands:
            if isinstance(command, Command):
                assert not command.name == 'help', "Command name 'help' is reserved."
                self.commands[command.name] = command
            elif callable(command):
                cmd = Command.from_function(command)
                assert not cmd.name == 'help', "Command name 'help' is reserved."
                self.commands[cmd.name] = cmd
            else:
                raise TypeError(f"Expected Command or callable, got {type(command)}")
        return self

    def get(self, name: str) -> Optional[Command]:
        if name == 'help':
            return Command(
                name='help',
                description='Show this help message.',
                handler=lambda agent: agent.display.info(
                    "Available commands:\n---\n" + "\n".join([f"> {cmd.name}: {cmd.description}" for cmd in self.commands.values()])
                )
            )
        return self.commands.get(name)
    
    def with_defaults(self):
        self.register(*default_commands())
        return self

def default_commands() -> list[Command]:
    from .store import Store
    from .display_abstract import ShowHistoryEvent

    def _restart_handler(agent: Agent) -> None:
        agent.conversation.clear()
        agent.display.info("Conversation history cleared.")
    
    def _revise_handler(agent: Agent) -> None:
        records = agent.conversation.pop_from_last_user_message()
        assert records and isinstance(records, list) and len(records) > 0 and isinstance(records[0], dict) and records[0].get("role") == "user"
        msg = agent.conversation.content_to_text(records[0].get("content", ""), truncate=True)
        agent.display.info(f"Cleared to last user message. (Poped: {msg[:50] + '...' if len(msg) > 50 else msg})")
    
    def _retry_handler(agent: Agent) -> None:
        agent.conversation.pop_from_last_user_message(inclusive=False)
        agent.display.info("Cleared to last user message.")
    
    def _config_handler(agent: Agent) -> None:
        config = agent.app_config
        agent.display.info(str(config.dict()))
    
    def _tools_handler(agent: Agent) -> None:
        tools = agent.toolbox.list_tools()
        if not tools:
            agent.display.info("No tools registered.")
            return
        agent.display.info("\n".join([f"{tool.name}: {tool.description}" for tool in tools]))
    
    def _dump_handler(agent: Agent) -> None:
        store = Store()
        agent.dump(aim_dir:=store.next_history_store())
        agent.display.info(f"Conversation history dumped to {aim_dir}")
    
    def _load_handler(agent: Agent, arguments: Optional[str]) -> None:
        if arguments:
            aim_dir = Path(arguments)
            if not aim_dir.exists():
                agent.display.error(f"File {aim_dir} does not exist.")
                return
            if not aim_dir.is_dir():
                agent.display.error(f"{aim_dir} is not a directory.")
                return
        else:
            store = Store()
            latest_dir = store.latest_history_store()
            if latest_dir is None:
                agent.display.info("No conversation history found.")
                return
            aim_dir = latest_dir
        agent.load(aim_dir)
        agent.display.info(f"Conversation history loaded from {aim_dir}")
    
    def _condense_handler(agent: Agent) -> None:
        agent.condense_conversation()
    
    def _history_handler(agent: Agent) -> None:
        agent.display.emit(
            ShowHistoryEvent(history=agent.conversation.to_history())
        )
    
    return [
        Command(name="restart", description="Clear the conversation history.", handler=_restart_handler),
        Command(name="revise", description="Clear to the last user message.", handler=_revise_handler),
        Command(name="retry", description="Retry the last user message.", handler=_retry_handler),
        Command(name="config", description="Show the current configuration.", handler=_config_handler),
        Command(name="tools", description="List all registered tools.", handler=_tools_handler),
        Command(name="dump", description="Dump the conversation history to a file.", handler=_dump_handler),
        Command(name="load", description="Load the conversation history from a file.", handler=_load_handler),
        Command(name="condense", description="Condense the conversation history.", handler=_condense_handler),
        Command(name="history", description="Show the conversation history.", handler=_history_handler),
    ]
    