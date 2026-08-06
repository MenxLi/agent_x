from __future__ import annotations
from typing import Generic, TypeVar, Optional, TYPE_CHECKING, Sequence
from abc import ABC, abstractmethod
from pydantic import BaseModel
from pathlib import Path
from .command import Command
from .conversation import Conversation
from .types import JsonType
if TYPE_CHECKING:
    from .agent import Agent

class ModelWorkingEvent(BaseModel):
    model_call_id: str
    remaining_iterations: Optional[int] = None

class ModelMessageEvent(BaseModel):
    model_call_id: str
    content: str

class ToolCallEvent(BaseModel):
    tool_call_id: str
    tool_name: str
    args: dict[str, JsonType]

class ToolResultEvent(BaseModel):
    tool_call_id: str
    result: JsonType

class ShowHistoryEvent(BaseModel):
    history: list[Conversation.MessageRecord]

class ShowHelpEvent(BaseModel):
    class _HelpCommand(BaseModel):
        name: str
        description: str

    commands: list[_HelpCommand] = []

    @classmethod
    def from_commands(cls, cmds: Sequence[Command]) -> "ShowHelpEvent":
        return cls(commands=[
            cls._HelpCommand(
                name=cmd.name, 
                description=cmd.description
                ) for cmd in cmds
            ])

class InfoEvent(BaseModel):
    message: str

class WarningEvent(BaseModel):
    message: str

class ErrorEvent(BaseModel):
    message: str

DisplayEventType = (
    ShowHelpEvent
    | ShowHistoryEvent
    | ModelWorkingEvent
    | ModelMessageEvent
    | ToolCallEvent
    | ToolResultEvent
    | InfoEvent
    | WarningEvent
    | ErrorEvent
)
DisplayEventT = TypeVar("DisplayEventT", bound=DisplayEventType)

class AgentInfo(BaseModel):
    name: str
    identifier: str
    workdir: Path
    @staticmethod
    def from_agent(agent: Agent) -> AgentInfo:
        return AgentInfo(name=agent.name, identifier=agent.identifier, workdir=agent.workdir)

class DisplayEvent(BaseModel, Generic[DisplayEventT]):
    agent: Optional[AgentInfo]
    event: DisplayEventT

def assemble_event(event: DisplayEventT) -> DisplayEvent[DisplayEventT]:
    from .context import execution_context
    if (ctx := execution_context.get()) is not None:
        agent_info = AgentInfo.from_agent(ctx.agent)
    else:
        agent_info = None
    return DisplayEvent(agent=agent_info, event=event)

class DisplayAbstract(ABC):
    @abstractmethod
    def get_confirm(
        self,
        prompt: str,
        message: Optional[str] = None, 
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        default: bool = True, 
        ) -> bool:...

    def emit(self, ev: DisplayEventType):
        event = assemble_event(ev)
        self.on_event(event)

    def info(self, message: str):
        self.emit(InfoEvent(message=message))

    def warning(self, message: str):
        self.emit(WarningEvent(message=message))

    def error(self, message: str):
        self.emit(ErrorEvent(message=message))

    @abstractmethod
    def on_event(self, event: DisplayEvent): ...

class NullDisplay(DisplayAbstract):
    def get_confirm( self, *args, **kwargs) -> bool:
        raise NotImplementedError("NullDisplay does not support get_confirm.")

    def on_event(self, event: DisplayEvent):
        pass