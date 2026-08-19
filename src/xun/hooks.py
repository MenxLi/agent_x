from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Any, TYPE_CHECKING, Optional
from pydantic import BaseModel
from .error_catch import except_safe
if TYPE_CHECKING:
    from openai.types.chat.chat_completion_message_function_tool_call import ChatCompletionMessageFunctionToolCall
    from .agent import Agent
    from .toolbox import ToolResultType

type HookProtocol[T] = Callable[[T], Any]
    
@dataclass
class ExecutionLoopParams:
    agent: Agent[Agent.T.Init]
    schema: Optional[type[BaseModel]]
    max_iterations: int
    context_value: Any = None

class HookArgs:

    # BeforeExecutionArgs = ExecutionLoopParams
    @dataclass
    class BeforeExecutionArgs:
        agent: "Agent[Agent.T.Init]"
        schema: Optional[type[BaseModel]]
        max_iterations: int
        context_value: Any = None

    @dataclass
    class BeforeToolCallArgs:
        agent: "Agent[Agent.T.Init]"

        tool_calls: list[ChatCompletionMessageFunctionToolCall]
        """list of tool calls that will be executed, editable"""

    @dataclass
    class AfterToolCallArgs:
        agent: "Agent[Agent.T.Init]"

        tool_results: list[tuple[str, ToolResultType]]
        """(tool_id, tool_result) pairs, editable"""

    @dataclass
    class AfterExecutionStepArgs:
        agent: "Agent[Agent.T.Init]"

    @dataclass
    class AfterInitializeArgs:
        agent: "Agent[Agent.T.Init]"

    @dataclass
    class BeforeFinalizeArgs:
        agent: "Agent[Agent.T.Init]"
    
    @dataclass
    class TextDelta:
        agent: "Agent[Agent.T.Init]"
        model_call_id: str
        content: str

@dataclass
class HookCallback[T]:
    fn: HookProtocol[T]
    persistent: bool

class HookRegistry[T]:
    def __init__(self):
        self._callbacks: list[HookCallback[T]] = []
    
    def add(self, fn: HookProtocol[T]):
        wrapped_fn = except_safe(fn)
        self._callbacks.append(HookCallback(wrapped_fn, True))
    
    def add_once(self, fn: HookProtocol[T]):
        wrapped_fn = except_safe(fn)
        self._callbacks.append(HookCallback(wrapped_fn, False))
    
    def invoke(self, args: T):
        for cb in self._callbacks:
            cb.fn(args)
        self._callbacks = [cb for cb in self._callbacks if cb.persistent]

@dataclass
class Hooks:
    before_execution: HookRegistry[HookArgs.BeforeExecutionArgs] = field(default_factory=HookRegistry)
    """Called at the start of an execution loop, before the first model call. Receives the `ExecutionLoopParams`, editable in place."""

    before_tool_call: HookRegistry[HookArgs.BeforeToolCallArgs] = field(default_factory=HookRegistry)
    after_tool_call: HookRegistry[HookArgs.AfterToolCallArgs] = field(default_factory=HookRegistry)
    after_execution_step: HookRegistry[HookArgs.AfterExecutionStepArgs] = field(default_factory=HookRegistry)
    """Called after each execution step, after tool results are added to the conversation and before the next model call is made."""

    after_initialize: HookRegistry[HookArgs.AfterInitializeArgs] = field(default_factory=HookRegistry)
    before_finalize: HookRegistry[HookArgs.BeforeFinalizeArgs] = field(default_factory=HookRegistry)

    model_text_delta: HookRegistry[HookArgs.TextDelta] = field(default_factory=HookRegistry)
    """Called before the model text delta is applied, allowing modification of the content. """

    model_reasoning_delta: HookRegistry[HookArgs.TextDelta] = field(default_factory=HookRegistry)
    """Called before the model reasoning delta is applied, allowing modification of the content. """