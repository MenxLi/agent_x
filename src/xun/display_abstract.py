from __future__ import annotations
from typing import Generic, TypeVar, Optional, TYPE_CHECKING, Sequence, Annotated
from abc import ABC, abstractmethod
from pydantic import BaseModel, PlainSerializer
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
            cls._HelpCommand(name="help", description="Show this help message."),
            *[
            cls._HelpCommand(
                name=cmd.name, 
                description=cmd.description
                ) for cmd in cmds
            ],
            ])

class CommandEvent(BaseModel):
    name: str
    arguments: Optional[str] = None

class InfoEvent(BaseModel):
    message: str

class WarningEvent(BaseModel):
    message: str

class ErrorEvent(BaseModel):
    message: str

DisplayEventType = (
    ShowHelpEvent
    | CommandEvent
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

def _ser_path(path: Path) -> str:
    return str(path.resolve())

class AgentInfo(BaseModel):
    name: str
    identifier: str
    workdir: Annotated[Path, PlainSerializer(_ser_path)]
    @staticmethod
    def from_agent(agent: Agent) -> AgentInfo:
        return AgentInfo(name=agent.name, identifier=agent.identifier, workdir=agent.workdir)

class DisplayEvent(BaseModel, Generic[DisplayEventT]):
    name: str
    agent: Optional[AgentInfo]
    event: DisplayEventT

    def to_json(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_json(cls, data: dict) -> DisplayEvent:
        event_name = data.get("name")
        if not event_name:
            raise ValueError("Missing 'name' field in DisplayEvent JSON data")
        event_cls = globals().get(event_name)
        if not event_cls or not issubclass(event_cls, BaseModel):
            raise ValueError(f"Unknown event type: {event_name}")
        event_data = data.get("event", {})
        agent_data = data.get("agent")
        agent_info = AgentInfo(**agent_data) if agent_data else None
        return cls(
            name=event_name,
            agent=agent_info,
            event=event_cls(**event_data)   # type: ignore
        )

def assemble_event(event: DisplayEventT) -> DisplayEvent[DisplayEventT]:
    from .context import execution_context
    if (ctx := execution_context.get()) is not None:
        agent_info = AgentInfo.from_agent(ctx.agent)
    else:
        agent_info = None
    return DisplayEvent(
        name=event.__class__.__name__,
        agent=agent_info, 
        event=event
        )

class DisplayAbstract(ABC):

    def bind_agent(self, agent: Agent) -> None:
        """Bind the owning agent when a display needs interactive input."""

    @abstractmethod
    def on_event(self, event: DisplayEvent): ...

    @abstractmethod
    def get_choice(
        self, 
        prompt: str,
        choices: list[str],
        message: Optional[str] = None,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        default: Optional[str] = None,
        allow_extra: bool = False,
        ) -> str: ...

    # may override this method
    def get_confirm(
        self,
        prompt: str,
        message: Optional[str] = None, 
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        default: bool = True, 
        ) -> bool:
        choice = self.get_choice(
            prompt=prompt,
            choices=["Yes", "No"],
            message=message,
            title=title,
            subtitle=subtitle,
            default="Yes" if default else "No",
            allow_extra=False
        )
        return choice == "Yes"

    def emit(self, ev: DisplayEventType):
        event = assemble_event(ev)
        self.on_event(event)

    def info(self, message: str):
        self.emit(InfoEvent(message=message))

    def warning(self, message: str):
        self.emit(WarningEvent(message=message))

    def error(self, message: str):
        self.emit(ErrorEvent(message=message))