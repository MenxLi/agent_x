from __future__ import annotations
from typing import TYPE_CHECKING, Optional, Callable, Any
import inspect
import shlex
from .context import context_agent
if TYPE_CHECKING:
    from .agent import Agent

type CommandHandlerWArgs = Callable[["Agent[Agent.T.Init]", list[str]], Any]
type CommandHandlerWOArgs = Callable[["Agent[Agent.T.Init]"], Any]
type CommandHandler = CommandHandlerWArgs | CommandHandlerWOArgs

class Command:
    _run: CommandHandlerWArgs
    name: str
    description: str
    description_long: Optional[str]

    def __init__(
        self,
        name: str,
        handler: CommandHandler,
        description: str = "",
        description_long: Optional[str] = None,
    ) -> None:
        self.name = name

        n_args_accepted = len(inspect.signature(handler).parameters)
        if n_args_accepted == 1:
            self._run = lambda agent, _arguments=None: handler(agent)  # type: ignore[misc]
        elif n_args_accepted == 2:
            self._run = lambda agent, arguments=None: handler(agent, arguments)  # type: ignore[misc]
        else:
            raise TypeError(f"Command handler must accept 1 or 2 args, got {n_args_accepted}")

        if not description:
            func_doc = (handler.__doc__ or "").strip() or "No description provided."
            description = func_doc.splitlines()[0]  # Use the first line of the docstring as the description

            if not description_long:
                description_long = func_doc if len(func_doc.splitlines()) > 1 else None

        self.description = description
        self.description_long = description_long

    def __repr__(self) -> str:
        return f"Command(name={self.name!r}, description={self.description!r})"
    
    @staticmethod
    def from_function(func: CommandHandler) -> Command:
        return Command(
            name=func.__name__,
            handler=func
        )

    def invoke(self, agent: "Agent[Agent.T.Init]", arguments: Optional[str] = None) -> None:
        args = shlex.split(arguments) if arguments else []
        if args in (["-h"], ["--help"]):
            with context_agent(agent):
                if self.description_long:
                    agent.info(self.description_long)
                else:
                    agent.info(self.description)
            return
        self._run(agent, args)

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
                agent.info(f"Tokens used in conversation: {token:.2f}{token_str_unit}")
            else:
                agent.info(f"Tokens used in conversation: {token}")
        else:
            agent.info("Tokens used in conversation: Unknown (not yet calculated)")

    def _restart_handler(agent: "Agent[Agent.T.Init]") -> None:
        agent.conversation.clear()
        agent.info("History cleared.")

    def _revise_handler(agent: "Agent[Agent.T.Init]") -> None:
        records = agent.conversation.pop_from_last_user_message()
        assert records and isinstance(records, list) and len(records) > 0 and isinstance(records[0], dict) and records[0].get("role") == "user"
        agent.info("Revised to last user message.")

    def _retry_handler(agent: "Agent[Agent.T.Init]") -> None:
        agent.conversation.pop_from_last_user_message(inclusive=False)
        agent.info("Restarted from last user message.")

    def _config_handler(agent: "Agent[Agent.T.Init]") -> None:
        agent.info(str(agent.config.to_json()))

    def _tools_handler(agent: "Agent[Agent.T.Init]") -> None:
        agent.display.emit(ShowToolsEvent.from_tools(agent.toolbox.list_tools()))

    def _dump_handler(agent: "Agent[Agent.T.Init]") -> None:
        store = Store()
        agent.dump(aim_dir := store.next_history_store())
        agent.info(f"Dumped to {aim_dir}")

    def _load_handler(agent: "Agent[Agent.T.Init]", idx: list[str]) -> None:
        store = Store()
        if not idx:
            agent.error("Please provide an index or 'latest/running' to load history.")
            return
        target = idx[0]
        if target.isdigit():
            aim_dir = store.get_history_store(target)
            if not aim_dir:
                agent.error(f"History {target} not found.")
                return
        elif target == "running":
            aim_dir = store.running_agent_store
        elif target == "latest":
            latest_dir = store.latest_history_store()
            if latest_dir is None:
                agent.info("No history found.")
                return
            aim_dir = latest_dir
        else:
            agent.error(f"Invalid index '{target}'. Use a number, 'latest', or 'running'.")
            return
        agent.load(aim_dir)
        agent.info(f"Loaded from {aim_dir}")

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