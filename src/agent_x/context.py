from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING
import contextvars
if TYPE_CHECKING:
    from .agent import Agent

@dataclass
class ToolCallContext:
    agent: "Agent"
tool_call_context = contextvars.ContextVar[Optional[ToolCallContext]]("tool_call_context", default=None)

@dataclass
class ExecutionContext:
    agent: "Agent"
execution_context = contextvars.ContextVar[Optional[ExecutionContext]]("execution_context", default=None)