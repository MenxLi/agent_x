
from __future__ import annotations
from typing import Generic, TypeVar, Optional, TYPE_CHECKING
from abc import ABC, abstractmethod
from pydantic import BaseModel
from pathlib import Path
from .conversation import Conversation
if TYPE_CHECKING:
    from .agent import Agent
# https://pydantic.dev/docs/validation/latest/concepts/types/#named-recursive-types
import sys
if sys.version_info >= (3, 12):
    type JsonType = str | int | float | bool | None | dict[str, JsonType] | list[JsonType]
else:
    from typing import Union
    from typing_extensions import TypeAliasType
    JsonType = TypeAliasType(
        'JsonType',
        'Union[dict[str, JsonType], list[JsonType], str, int, float, bool, None]',  
    )


class InfoEvent(BaseModel):
    message: str

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
    | ErrorEvent
    )
DisplayEventT = TypeVar( "DisplayEventT", bound=DisplayEventType)

class AgentInfo(BaseModel):
    name: str
    identifier: str
    workdir: Path
    @staticmethod
    def from_agent(agent: Agent) -> AgentInfo:
        return AgentInfo(
            name=agent.name,
            identifier=agent.identifier,
            workdir=agent.workdir,
        )
class DisplayEvent(BaseModel, Generic[DisplayEventT]):
    agent: Optional[AgentInfo]
    event: DisplayEventT

class MessageInstruction(BaseModel):
    content: str
    images: list[str] = []
class CommandInstruction(BaseModel):
    command: str
    args: list[str] = []
Instruction = MessageInstruction | CommandInstruction

def assemble_event(event: DisplayEventT) -> DisplayEvent[DisplayEventT]:
    from .context import execution_context
    if (ctx := execution_context.get()) is not None:
        agent_info = AgentInfo.from_agent(ctx.agent)
    else:
        agent_info = None
    return DisplayEvent(
        agent=agent_info,
        event=event,
    )

class DisplayAbstract(ABC):
    @abstractmethod
    def get_instruction(self) -> Instruction:...

    @abstractmethod
    def get_confirm(
        self,
        prompt: str,
        message: Optional[str] = None, 
        title: Optional[str] = None,
        subtitle: str | None = None,
        default: bool = True, 
        ) -> bool:...

    def emit(self, ev: DisplayEventType):
        event = assemble_event(ev)
        self.on_event(event)
    
    def info(self, message: str):
        self.emit(InfoEvent(message=message))
    
    def error(self, message: str):
        self.emit(ErrorEvent(message=message))

    @abstractmethod
    def on_event(self, event: DisplayEvent):...
