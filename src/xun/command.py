from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, Callable, Any
import inspect
if TYPE_CHECKING:
    from .agent import Agent

type CommandHandlerWArgs = Callable[["Agent[Agent.T.Init]", Optional[str]], Any]
type CommandHandlerWOArgs = Callable[["Agent[Agent.T.Init]"], Any]
type CommandHandler = CommandHandlerWArgs | CommandHandlerWOArgs

@dataclass
class Command:
    name: str
    description: str
    handler: CommandHandler
    _runner: Callable[["Agent[Agent.T.Init]", Optional[str]], None] = field(init=False, repr=False)

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
        return Command(
            name=func.__name__,
            description=func.__doc__ or "No description provided.",
            handler=func
        )

    def invoke(self, agent: "Agent[Agent.T.Init]", arguments: Optional[str] = None) -> None:
        self._runner(agent, arguments)

class CommandRegistry:
    def __init__(self):
        self.commands: dict[str, Command] = {}

    def register(self, *commands: Command | CommandHandler):
        for command in commands:
            if isinstance(command, Command):
                assert command.name != 'help', "Command name 'help' is reserved."
                self.commands[command.name] = command
            elif callable(command):
                cmd = Command.from_function(command)
                assert cmd.name != 'help', "Command name 'help' is reserved."
                self.commands[cmd.name] = cmd
            else:
                raise TypeError(f"Expected Command or callable")
        return self

    def get(self, name: str) -> Optional[Command]:
        from .display_abstract import ShowHelpEvent
        if name == 'help':
            return Command(
                name='help',
                description='Show this help message.',
                handler=lambda agent: agent.display.emit(
                    ShowHelpEvent.from_commands(tuple(self.commands.values()))
                )
            )
        return self.commands.get(name)

    def with_defaults(self):
        self.register(*default_commands())
        return self

def default_commands() -> list[Command]:
    from .store import Store
    from .display_abstract import ShowHistoryEvent, ShowToolsEvent
    
    def _token_query_handler(agent: "Agent[Agent.T.Init]") -> None:
        token = agent.conversation.total_tokens
        if token is not None:
            token_str_unit = ""
            if token >= 1000:
                token_str_unit = "K"
                token /= 1000
            if token >= 1000:
                token_str_unit = "M"
                token /= 1000

            if token_str_unit:
                agent.display.info(f"Tokens used in conversation: {token:.2f}{token_str_unit}")
            else:
                agent.display.info(f"Tokens used in conversation: {token}")
        else:
            agent.display.info("Tokens used in conversation: Unknown (not yet calculated)")

    def _restart_handler(agent: "Agent[Agent.T.Init]") -> None:
        agent.conversation.clear()
        agent.display.info("History cleared.")

    def _revise_handler(agent: "Agent[Agent.T.Init]") -> None:
        records = agent.conversation.pop_from_last_user_message()
        assert records and isinstance(records, list) and len(records) > 0 and isinstance(records[0], dict) and records[0].get("role") == "user"
        agent.display.info("Revised to last user message.")

    def _retry_handler(agent: "Agent[Agent.T.Init]") -> None:
        agent.conversation.pop_from_last_user_message(inclusive=False)
        agent.display.info("Restarted from last user message.")

    def _config_handler(agent: "Agent[Agent.T.Init]") -> None:
        agent.display.info(str(agent.config.to_json()))

    def _tools_handler(agent: "Agent[Agent.T.Init]") -> None:
        agent.display.emit(ShowToolsEvent.from_tools(agent.toolbox.list_tools()))

    def _dump_handler(agent: "Agent[Agent.T.Init]") -> None:
        store = Store()
        agent.dump(aim_dir := store.next_history_store())
        agent.display.info(f"Dumped to {aim_dir}")

    def _load_handler(agent: "Agent[Agent.T.Init]", idx: Optional[str]) -> None:
        store = Store()
        if idx is None:
            agent.display.error("Please provide an index or 'latest/running' to load history.")
            return
        if idx.isdigit():
            aim_dir = store.get_history_store(idx)
            if not aim_dir:
                agent.display.error(f"History {idx} not found.")
                return
        elif idx == "running":
            aim_dir = store.running_agent_store
        elif idx == "latest":
            latest_dir = store.latest_history_store()
            if latest_dir is None:
                agent.display.info("No history found.")
                return
            aim_dir = latest_dir
        else:
            agent.display.error(f"Invalid index '{idx}'. Use a number, 'latest', or 'running'.")
            return
        agent.load(aim_dir)
        agent.display.info(f"Loaded from {aim_dir}")

    def _condense_handler(agent: "Agent[Agent.T.Init]") -> None:
        agent.condense_conversation()

    def _history_handler(agent: "Agent[Agent.T.Init]") -> None:
        agent.display.emit(ShowHistoryEvent(history=agent.conversation.to_history()))

    return [
        Command(name="tokens", description="Show tokens used in conversation.", handler=_token_query_handler),
        Command(name="clear", description="Clear conversation history.", handler=_restart_handler),
        Command(name="revise", description="Edit last message.", handler=_revise_handler),
        Command(name="retry", description="Retry last message.", handler=_retry_handler),
        Command(name="config", description="Show configuration.", handler=_config_handler),
        Command(name="tools", description="List registered tools.", handler=_tools_handler),
        Command(name="save", description="Save history.", handler=_dump_handler),
        Command(name="load", description="Load history. (running, latest, [idx])", handler=_load_handler),
        Command(name="compact", description="Condense conversation.", handler=_condense_handler),
        Command(name="history", description="Show history.", handler=_history_handler),
    ]