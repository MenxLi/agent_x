from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING
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
