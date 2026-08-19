from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING
from contextlib import contextmanager
import contextvars
if TYPE_CHECKING:
    from .agent import Agent
    from .display_abstract import DisplayAbstract

@dataclass
class ExecutionContext:
    agent: "Agent[Agent.T.Any]"

    @property
    def display(self) -> "DisplayAbstract":
        return self.agent.display

execution_context = contextvars.ContextVar[Optional[ExecutionContext]]("execution_context", default=None)

@contextmanager
def context_agent(agent: "Agent[Agent.T.Any]"):
    """Set `execution_context` to `agent` for the duration of the block,
    restoring the previous context on exit."""
    prev_context = execution_context.get()
    execution_context.set(ExecutionContext(agent=agent))
    try:
        yield
    finally:
        execution_context.set(prev_context)
