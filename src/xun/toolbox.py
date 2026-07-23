from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .agent import Agent
from typing import Callable, TypeVar
import fnmatch
from openai.types import chat
from .tools import *
from .prompt import get_subagent_prompt
from .error_catch import except_safe, is_except_safe_wrapper
from ._toolcall_fix import extract_tool_calls_from_text
from .toolbox_lib import Function

F = TypeVar("F", bound=Callable)
class ToolBox:
    STANDARD_TOOL_FACTORIES: list[Callable[[], list[Callable]]] = [
        expose_system_tools,
        expose_fs_tools, 
        expose_cmd_tools,
        expose_search_tools,
        expose_browser_tools,
    ]

    def __init__(self):
        self._tools: dict[str, Function] = {}
        self._disabled_tools: set[str] = set()
    
    def clone(self) -> "ToolBox":
        import copy
        new_box = ToolBox()
        new_box._tools = copy.copy(self._tools)
        new_box._disabled_tools = copy.deepcopy(self._disabled_tools)
        return new_box
    
    def with_defaults(self):
        """
        Register all standard tools provided by the system. 
        Call this method to quickly set up a toolbox with a wide range of capabilities for your agent.
        """
        for tool_set_fn in self.STANDARD_TOOL_FACTORIES:
            tool_set = tool_set_fn()
            self.register_many(tool_set)
        return self
    
    def register(self, f: F) -> F:
        fn = f if is_except_safe_wrapper(f) else except_safe(f)
        wrapped = Function.from_function(fn)
        self._tools[wrapped.name] = wrapped
        return f
    
    def register_many(self, funcs: list[Callable]) -> list[Callable]:
        return [ self.register(func) for func in funcs ]
    
    def with_subagent_provider(self, agent_getter: Callable[[], "Agent"] | None = None):
        """
        Allow the agent to spawn sub-agents (worker) to execute tasks. 
        The sub-agents can be customized by providing an agent_getter function.
        """
        if agent_getter is None:
            def _agent_getter():
                from .agent import Agent    # avoid circular import
                from .context import tool_call_context
                tool_context = tool_call_context.get()
                if tool_context is None:
                    raise RuntimeError("tool_call_context is not set, cannot create sub-agent")
                return Agent.inherit(tool_context.agent).system(get_subagent_prompt())
            agent_getter = _agent_getter
        self.register(agent_run_factory(agent_getter))
        self.register(agent_run_parallel_factory(agent_getter))
        return self

    def _resolve_tool_names(self, *patterns: str) -> set[str]:
        """ Resolve names/glob-patterns to a set of actual tool names.  
        Plain names are returned as-is.  """
        WILDCARD_CHARS = frozenset("*?[]")

        # fast path: no wildcards at all
        if not any(WILDCARD_CHARS & set(p) for p in patterns):
            return set(patterns)

        all_names = set(self._tools) | self._disabled_tools
        resolved: set[str] = set()
        for pattern in patterns:
            if WILDCARD_CHARS & set(pattern):
                for name in all_names:
                    if fnmatch.fnmatch(name, pattern):
                        resolved.add(name)
            else:
                resolved.add(pattern)
        return resolved

    def disable(self, *tool_names: str) -> "ToolBox":
        """Disable tools by exact name or glob pattern. wildcard patterns are supported."""
        self._disabled_tools.update(self._resolve_tool_names(*tool_names))
        return self
    
    def enable(self, *tool_names: str) -> "ToolBox":
        """Enable previously-disabled tools by exact name or glob pattern. wildcard patterns are supported."""
        self._disabled_tools.difference_update(self._resolve_tool_names(*tool_names))
        return self
    
    def list_tools(self):
        return [
            tool
            for name, tool in self._tools.items()
            if name not in self._disabled_tools
        ]
    
    def call_tool(self, tool_name: str, arguments: dict):
        if tool_name in self._disabled_tools:
            raise ValueError(f"Tool '{tool_name}' is disabled.")
        tool = self._tools.get(tool_name)
        if tool is None:
            raise ValueError(f"Tool '{tool_name}' is not registered.")
        return tool.call(arguments)

    def list_tools_json(self):
        return [tool.tool_schema for tool in self.list_tools()]
    

def extract_tool_calls(choice: chat.chat_completion.Choice) -> chat.chat_completion.Choice:
    if choice.message.tool_calls:
        return choice

    # https://github.com/vllm-project/vllm/issues/39056
    # https://github.com/vllm-project/vllm/issues/29192

    content = choice.message.content
    if content is None:
        return choice

    cleaned, tool_calls = extract_tool_calls_from_text(content)

    choice.message.content = cleaned
    # dict to list of ToolCall
    tool_calls_typed: list[chat.chat_completion_message_function_tool_call.ChatCompletionMessageFunctionToolCall] = []
    for tc in tool_calls:
        tool_calls_typed.append(
            chat.chat_completion_message_function_tool_call.ChatCompletionMessageFunctionToolCall(
                id=tc["id"],
                type="function",
                function=chat.chat_completion_message_function_tool_call.Function(
                    name=tc["function"]["name"],
                    arguments=tc["function"]["arguments"],
                ),
            )
        )
    
    choice.message.tool_calls = tool_calls_typed    # type: ignore
    return choice
