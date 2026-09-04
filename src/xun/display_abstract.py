from __future__ import annotations
from typing import Generic, Optional, TYPE_CHECKING, Sequence, Annotated, Literal
import time
from abc import ABC, abstractmethod
from pydantic import BaseModel, Field, PlainSerializer
from pathlib import Path
from PIL.Image import Image
from .command import Command
from .types import JsonType, ModelCapabilityType
from .util import image_to_url
from .conversation import Conversation
from .types import TypeVar
if TYPE_CHECKING:
    from .agent import Agent
    from .config import AgentConfig
    from .toolcall import Function

class ModelWorkingEvent(BaseModel):
    model_call_id: str
    remaining_iterations: Optional[int] = None

class ModelMessageEvent(BaseModel):
    model_call_id: str
    content: str
    reasoning: Optional[str] = None
    total_tokens: int
    """ Total tokens consumed by the conversation so far, as reported by the provider. """

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

class ShowToolsEvent(BaseModel):
    class ToolInfo(BaseModel):
        name: str
        description: str
        required_capabilities: list[ModelCapabilityType] = Field(default_factory=list)

    tools: list[ToolInfo] = Field(default_factory=list)

    @classmethod
    def from_tools(cls, tools: Sequence[Function]) -> "ShowToolsEvent":
        return cls(tools=[
            cls.ToolInfo(
                name=tool.name,
                description=tool.description,
                required_capabilities=sorted(tool.required_capabilities),
            )
            for tool in tools
        ])

class UserCommandEvent(BaseModel):
    name: str
    arguments: Optional[str] = None

class UserMessageEvent(BaseModel):
    class ImageDescriptor(BaseModel):
        kind: Literal["url", "base64"]
        value: str
    content: str
    images: list[ImageDescriptor] = Field(default_factory=list)

    @classmethod
    def from_inputs(
        cls,
        content: str,
        images: Sequence[str | Image] | None = None,
    ) -> "UserMessageEvent":
        return cls(
            content=content,
            images=[
                cls.ImageDescriptor(
                    kind="base64" if image_url.startswith("data:") else "url",
                    value=image_url,
                )
                for image_url in (image_to_url(image) for image in images or ())
            ],
        )

class InfoEvent(BaseModel):
    message: str

class WarningEvent(BaseModel):
    message: str

class ErrorEvent(BaseModel):
    message: str

class AgentBindEvent(BaseModel):
    ...

class AgentUnbindEvent(BaseModel):
    ...

DisplayEventType = (
    ShowHelpEvent
    | ShowToolsEvent
    | AgentBindEvent
    | AgentUnbindEvent
    | UserCommandEvent
    | UserMessageEvent
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
    def from_agent(agent: "Agent[Agent.T.Any]") -> AgentInfo:
        return AgentInfo(name=agent.name, identifier=agent.identifier, workdir=agent.workdir)

class DisplayEvent(BaseModel, Generic[DisplayEventT]):
    timestamp: float = Field(default_factory=lambda: time.time())
    """ The timestamp when the event was created, in seconds since the epoch.  """

    name: str
    """ The name of the event type, e.g. 'ModelMessageEvent', 'ToolCallEvent', etc. """

    agent: Optional[AgentInfo]
    """ The agent that is active when the event is emitted. """

    event: DisplayEventT
    """ The actual event data. """

    def to_json(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_json(cls, data: dict) -> DisplayEvent[DisplayEventT]:
        event_name = data.get("name")
        if not event_name:
            raise ValueError("Missing 'name' field in DisplayEvent JSON data")
        event_cls = globals().get(event_name)
        if not event_cls or not issubclass(event_cls, BaseModel):
            raise ValueError(f"Unknown event type: {event_name}")
        event_data = data.get("event", {})
        agent_data = data.get("agent")
        timestamp = data.get("timestamp", time.time())
        agent_info = AgentInfo(**agent_data) if agent_data else None
        return cls(
            name=event_name,
            agent=agent_info,
            timestamp=timestamp,
            event=event_cls(**event_data)   # type: ignore
        )

class DisplayAbstract(ABC):
    _agents: dict[str, "Agent[Agent.T.Any]"]

    def bind(self, agent: "Agent[Agent.T.Uninit]") -> None:
        self.agents[agent.identifier] = agent

    def unbind(self, agent: "Agent[Agent.T.Any]") -> None:
        if agent.identifier in self.agents:
            del self.agents[agent.identifier]
    
    @property
    def agents(self) -> dict[str, "Agent[Agent.T.Any]"]:
        """Return the dictionary of {identifier: Agent} for all agents bound to this display."""
        if hasattr(self, "_agents"):
            return self._agents
        else:
            setattr(self, "_agents", {})
            return self._agents

    @abstractmethod
    def on_event(self, event: DisplayEvent): ...
    """Handle an assembled event. The only entry point for events: builds
    via AgentDisplayMixin.display_event (agent-originated) or by the display
    itself for display-local events."""

    class ChoiceRequest(BaseModel):
        """A user-prompt request routed to the display that owns it.
        `agent_info` identifies which bound agent is asking, required by displays
        shared by multiple agents (e.g. WebDisplay)."""
        agent_info: AgentInfo
        prompt: str
        choices: list[str]
        message: Optional[str] = None
        title: Optional[str] = None
        subtitle: Optional[str] = None
        default: Optional[str] = None
        allow_extra: bool = False

    @abstractmethod
    def get_choice(self, request: ChoiceRequest) -> str: ...
    """Collect a choice from the user. Confirmation-style prompts
    (Yes/No) are handled by AgentDisplayMixin.get_confirm, on top of this method."""

class AgentDisplayMixin:
    """Display-facing helpers for Agent: event emission, messages and prompts.

    The attribute block below is a type-check-time contract declaring which
    parts of Agent the helpers use, so plain `self` type-checks without
    importing agent.py (which would be circular). At runtime the declarations
    do not exist; Agent provides the real attributes.
    """
    if TYPE_CHECKING:
        name: str
        identifier: str
        workdir: Path
        display: DisplayAbstract
        config: AgentConfig

    def _agent_info(self) -> AgentInfo:
        return AgentInfo(name=self.name, identifier=self.identifier, workdir=self.workdir)

    def display_event(self, ev: DisplayEventType) -> None:
        self.display.on_event(DisplayEvent(
            name=ev.__class__.__name__,
            agent=self._agent_info(),
            event=ev,
        ))

    def info(self, message: str) -> None:
        self.display_event(InfoEvent(message=message))

    def warning(self, message: str) -> None:
        self.display_event(WarningEvent(message=message))

    def error(self, message: str) -> None:
        self.display_event(ErrorEvent(message=message))

    def get_choice(
        self,
        prompt: str,
        choices: list[str],
        message: Optional[str] = None,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        default: Optional[str] = None,
        allow_extra: bool = False,
        ) -> str:
        """Ask the user to choose, honoring auto-confirm: return the default
        choice without prompting."""
        if self.config.auto_confirm:
            if default in choices:
                choice = default
            elif choices:
                choice = choices[0]
                self.warning(f"No default for prompt {prompt!r}; auto-selected {choice!r}.")
            else:
                raise ValueError(f"No choices available for prompt {prompt!r}")
            self.info(f"Auto-confirmed: {prompt} -> {choice}")
            return choice
        return self.display.get_choice(DisplayAbstract.ChoiceRequest(
            agent_info=self._agent_info(),
            prompt=prompt, choices=choices, message=message,
            title=title, subtitle=subtitle, default=default, allow_extra=allow_extra,
        ))

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
            message=message, title=title, subtitle=subtitle,
            default="Yes" if default else "No",
        )
        return choice == "Yes"