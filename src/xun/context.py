from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING
from threading import Lock
import contextvars
if TYPE_CHECKING:
    from .display_abstract import DisplayAbstract
    from .agent import Agent
    from .tempdir import DeferredTempDirectory

@dataclass
class ExecutionContext:
    agent: "Agent"

    @property
    def display(self) -> "DisplayAbstract":
        return self.agent.display

execution_context = contextvars.ContextVar[Optional[ExecutionContext]]("execution_context", default=None)

class Guarded[T]:
    def __init__(self, value: T):
        self.value = value
        self._lock = Lock()
    def __enter__(self):
        self._lock.acquire()
        return self.value
    def __exit__(self, exc_type, exc_val, exc_tb):
        self._lock.release()
@dataclass
class GlobalContext:
    tempdirs: set["DeferredTempDirectory"] = field(default_factory=set)

global_context_guard = Guarded(GlobalContext())