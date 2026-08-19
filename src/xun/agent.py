from __future__ import annotations
from typing import Any, Sequence, Optional, Generic, TypeGuard, cast, overload
from typing_extensions import TypeVar
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
import json
import uuid
import weakref

from openai import OpenAI
from pydantic import BaseModel
from PIL.Image import Image
from threading import Semaphore, Event

from .display_abstract import *
from .displays.display import Display
from .conversation import Conversation
from .config import app_config
from .prompt import get_condense_prompt
from .error_catch import except_safe
from .toolbox import ToolBox, extract_tool_calls
from .tempdir import DeferredTempDirectory
from .context import context_agent
from .command import CommandRegistry
from .hooks import Hooks, HookArgs
from .types import CancelledError
from .loop import execution_loop, ExecutionLoopParams

DEFAULT_MAX_ITERATIONS = 128

def _default_openai_client():
    config = app_config()
    return OpenAI(
        base_url = config.provider.openai_base_url,
        api_key = config.provider.openai_api_key,
    )
DEFAULT_API_CALL_LIMIT = 3

@dataclass
class LabeledEvent:
    label: str
    event: Event = field(default_factory=Event)

class _AgentState:
    """Type-state marker for the agent lifecycle. Type-level only, never instantiated."""

class _Uninit(_AgentState):
    """Constructed but not yet initialized (display unbound, store unloaded, workdir unprepared)."""

class _Init(_AgentState):
    """Initialized: display bound, persistent store loaded, workdir ready, after_initialize fired."""

class _Final(_AgentState):
    """Finalized: display unbound, before_finalize fired. The agent must not be used further."""

# covariant: an Agent[T.Init] is usable anywhere an Agent[T.Any] is expected,
# but not vice versa (you cannot pretend an initialized agent is a fresh one).
# default=_Uninit: a bare `Agent` (no subscript) denotes a freshly constructed agent,
# so `Agent(...)` yields Agent[T.Uninit] and callers cannot call execute until they
# observe initialize() (or use `with agent:`). State-agnostic code uses Agent[T.Any].
StateT = TypeVar("StateT", bound=_AgentState, covariant=True, default=_Uninit)

class _Life(IntEnum):
    """Runtime lifecycle state (mirrors the type-level T markers)."""
    UNINIT, INIT, FINAL = 0, 1, 2

class T:
    """
    Namespace for type-level lifecycle states for annotations: 
    `Agent[T.Uninit]` / `Agent[T.Init]` / ...
    """
    Uninit = _Uninit
    Init = _Init
    Final = _Final
    Alive = _Uninit | _Init
    Any = _AgentState

@dataclass
class Agent(Generic[StateT]):

    # class-level shorthand so callers can use `Agent[Agent.T.Init]`.
    # Must be a plain class attribute (NOT a PEP 695 `type` alias): a `type T = T`
    # turns Agent.T into a TypeAliasType whose attributes Pylance won't resolve.
    T = T

    name: str = field(default_factory=lambda: f"agent-{str(uuid.uuid4())[:8]}")
    identifier: str = field(default_factory=lambda: str(uuid.uuid4()))
    display: DisplayAbstract = field(default_factory=Display)
    conversation: Conversation = field(default_factory=Conversation)
    toolbox: ToolBox = field(default_factory=ToolBox)
    command: CommandRegistry = field(default_factory=CommandRegistry)
    workdir: Path = field(default_factory=lambda: Path.cwd())
    tempdir: DeferredTempDirectory = field(default_factory=DeferredTempDirectory)
    persistent_store: Optional[Path] = None
    cancel_event: LabeledEvent = field(default_factory=lambda: LabeledEvent(label=""))

    # below auto inherit
    openai_client: OpenAI = field(default_factory=_default_openai_client)
    api_call_semaphore: Semaphore = field(default_factory=lambda: Semaphore(DEFAULT_API_CALL_LIMIT))

    # below does not inherit
    state: dict[str, Any] = field(default_factory=dict)
    hooks: Hooks = field(default_factory=Hooks)

    _lifecycle: _Life = field(init=False, repr=False, default=_Life.UNINIT)

    def __post_init__(self):
        # Construction is side-effect free; call initialize() (or use `with agent:`)
        # to bind the display, load the persistent store, prepare the workdir, and fire after_initialize.
        if self.cancel_event.label == "":
            self.cancel_event.label = self.identifier

        # note: the callback must not hold a strong reference to the agent
        # (weakref.finalize keeps its arguments alive), hence the weakref idiom
        agent_ref = weakref.ref(self)
        weakref.finalize(self, Agent._finalize, agent_ref)

    def initialize(self: Agent[T.Uninit]) -> Agent[T.Init]:
        """
        Initialize the agent, cannot be called on a finalized agent. 
        Returns a Agent[T.Init]

        Must rebind (shadow) on call for proper type-level state, e.g.
        ```python
        agent = Agent()
        agent = agent.initialize()  # rebind
        ```
        """
        if self._lifecycle == _Life.FINAL:
            raise RuntimeError(f"Agent '{self.name}' has been finalized; it cannot be re-initialized.")
        if self._lifecycle == _Life.INIT:
            return cast(Agent[T.Init], self)
        with Agent.context_agent(self):
            self.display.bind(self)
            self.display.emit(AgentBindEvent())
        if self.persistent_store:
            if self.persistent_store.exists():
                assert self.persistent_store.is_dir(), f"Persistent store path {self.persistent_store} must be a directory."
                self.load(self.persistent_store)
            self.display.emit(InfoEvent(message=f"Using persistent store from {self.persistent_store}"))

        if self.workdir.exists():
            assert self.workdir.is_dir(), f"Workdir path {self.workdir} must be a directory."
        else:
            self.workdir.mkdir(parents=False, exist_ok=True)

        self._lifecycle = _Life.INIT
        initialized_self = cast(Agent[T.Init], self)
        self.hooks.after_initialize.invoke(HookArgs.AfterInitializeArgs(agent=initialized_self))
        return initialized_self

    @staticmethod
    def is_initialized(agent: Agent[T.Any]) -> TypeGuard[Agent[T.Init]]:
        """Type guard: True when the agent is initialized (and not finalized).

        Stands as a staticmethod (call as Agent.is_initialized(agent)) because Pylance only
        accepts user-defined TypeGuards with at least one explicit parameter.
        """
        return agent._lifecycle == _Life.INIT

    @staticmethod
    def is_finalized(agent: Agent[T.Any]) -> TypeGuard[Agent[T.Final]]:
        """Type guard: True when the agent has been finalized and must not be used further."""
        return agent._lifecycle == _Life.FINAL

    @property
    def app_config(self):
        return app_config()
    
    @staticmethod
    def inherit(
        parent_agent: Agent[T.Any], 
        share_tempdir: bool = True,
        share_display: bool = True,
        share_workdir: bool = True,
        share_cancel_event: bool = True,
        copy_toolbox: bool = True,
        copy_conversation: bool = False,
        copy_command: bool = True,
        persistent_store: Optional[Path] = None, 
        ) -> "Agent[T.Uninit]":
        """
        Create a new agent that inherits the configuration and state from the parent agent.
        The returned agent is NOT initialized; call initialize() (or use `with agent:`) before executing.
        """
        new_agent = Agent(
            identifier=(new_id := str(uuid.uuid4())),
            name=f"{parent_agent.name}-child-{new_id[:8]}",
            persistent_store=persistent_store,
            # auto inherit
            openai_client=parent_agent.openai_client,
            api_call_semaphore=parent_agent.api_call_semaphore,
            display=parent_agent.display if share_display else Display(),
        )
        if share_tempdir:
            new_agent.tempdir = parent_agent.tempdir
        if copy_toolbox:    
            new_agent.toolbox = parent_agent.toolbox.clone()
        if copy_command:
            new_agent.command = parent_agent.command
        if copy_conversation:
            new_agent.conversation.messages = parent_agent.conversation.messages.copy()
        if share_cancel_event:
            new_agent.cancel_event = parent_agent.cancel_event
        if share_workdir:
            new_agent.workdir = parent_agent.workdir
        return new_agent

    def dump(self, store_dir: Optional[Path] = None):
        if store_dir is None:
            if self.persistent_store is None:
                return
            store_dir = self.persistent_store
        if not store_dir.exists():
            store_dir.mkdir(exist_ok=True)

        conv_file = store_dir / f"conversation.json"
        self.conversation.dump(conv_file)
    
    def load(self, store_dir: Optional[Path] = None):
        if store_dir is None:
            if self.persistent_store is None:
                raise ValueError("Persistent store path is not set. Please provide a store_dir to load the conversation.")
            store_dir = self.persistent_store

        conv_file = store_dir / f"conversation.json"
        if conv_file.exists():
            self.conversation.load(conv_file)
        else:
            self.display.emit(ErrorEvent(message=f"No conversation history found in {conv_file}. Starting with an empty conversation."))
    
    def cancel(self):
        self.cancel_event.event.set()

    def check_cancel(self):
        if self.cancel_event.event.is_set():
            raise CancelledError("Operation cancelled by user.")

    @overload
    @except_safe
    def execute[T: BaseModel](
        self: Agent[Agent.T.Init], schema: type[T],  # explicit Agent.T: method typevar T shadows the module alias
        max_iterations: int = DEFAULT_MAX_ITERATIONS, 
        context: Any = None
    ) -> T: ...
    @overload
    @except_safe
    def execute(
        self: Agent[T.Init], schema: None = None, 
        max_iterations: int = DEFAULT_MAX_ITERATIONS, 
        context: Any = None
    ) -> str: ...
    @except_safe
    def execute(
        self: Agent[T.Init], schema: Optional[type[BaseModel]] = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        context: Any = None
        ):
        if not Agent.is_initialized(self):
            raise RuntimeError(f"Agent '{self.name}' is not initialized. Call agent.initialize() or use 'with agent:'.")

        return execution_loop(ExecutionLoopParams(
            agent=self, schema=schema, max_iterations=max_iterations, context_value=context
        ))

    def system[AliveT: Agent[T.Alive]](self: AliveT, content: str) -> AliveT:
        self.conversation.set_system_message_content(content)
        return self

    def instruct[AliveT: Agent[T.Alive]](
        self: AliveT,
        instruction: str,
        images: Sequence[str | Image] | None = None,
        _emit_event: bool = True,
    ) -> AliveT:
        self.conversation.add_user_message(instruction, images=images)
        if _emit_event:
            with Agent.context_agent(self):
                self.display.emit(UserMessageEvent.from_inputs(instruction, images=images))
        return self
    
    def execute_command(self: "Agent[T.Init]", command_name: str, arguments: Optional[str] = None):
        command = self.command.get(command_name)
        with Agent.context_agent(self):
            self.display.emit(UserCommandEvent(name=command_name, arguments=arguments))
        if command is None:
            self.display.error(f"Unknown command: {command_name}")
            return
        try:
            command.invoke(self, arguments)
        except Exception as e:
            self.display.error(f"Error executing command '{command_name}': {e}")
    
    def condense_conversation(self: "Agent[T.Init]"):
        _condense_conversation(self)
    
    def __enter__(self: "Agent[T.Uninit]") -> "Agent[T.Init]":
        # any state: entering an already-initialized agent (e.g. a configured one returned
        # by a sub-agent getter) is fine because initialize() is runtime-idempotent.
        return self.initialize()
    
    def __exit__(self: Agent[T.Alive], exc_type, exc_value, traceback):
        if Agent.is_initialized(self):
            self.finalize()
    
    def finalize(self: Agent[T.Alive]) -> Agent[T.Final]:
        """
        Finalize the agent, 
        cannot use the agent after finalization. Returns a Agent[T.Final].

        Must rebind on call for proper type-level state, like initialize().
        """
        if self._lifecycle == _Life.FINAL:
            return cast("Agent[T.Final]", self)
        was_init = self._lifecycle == _Life.INIT
        self._lifecycle = _Life.FINAL
        if was_init:
            with Agent.context_agent(self):
                # was_init implies self is Agent[T.Init] (self is Agent[T.Alive] here)
                self.hooks.before_finalize.invoke(HookArgs.BeforeFinalizeArgs(agent=cast("Agent[T.Init]", self)))
                self.display.unbind(self)
                self.display.emit(AgentUnbindEvent())
        return cast("Agent[T.Final]", self)

    @staticmethod
    def _finalize(agent_ref: "weakref.ref"):
        # weakref callback: the agent's state is unknown at GC time
        if (agent := agent_ref()) is not None and Agent.is_initialized(agent):
            agent.finalize()
    
    @staticmethod
    def context_agent(agent: Agent[T.Any]):
        """Scope `execution_context` to `agent`; delegates to context.context_agent."""
        return context_agent(agent)

def _condense_conversation(agent: "Agent[Agent.T.Init]"):
    """
    Condense the conversation history of the agent by keeping only the last user message and the assistant messages after that. 
    """
    agent.display.emit(InfoEvent(message="Condensing conversation history..."))

    keep_messages = agent.conversation.pop_from_last_user_message()
    condense_messages = agent.conversation.messages
    
    if not condense_messages:
        # revert
        agent.conversation.messages = condense_messages + keep_messages
        return
    
    client = agent.openai_client
    condense_messages_json = json.dumps(condense_messages, indent=4)
    with agent.api_call_semaphore:
        resp = client.chat.completions.create(
            model=agent.app_config.provider.openai_model,
            messages = [
                {
                    "role": "user",
                    "content": get_condense_prompt(condense_messages_json),
                },
            ],
            timeout = 300,
        )
    summary = resp.choices[0].message.content
    if summary is None:
        agent.display.emit(ErrorEvent(message="Failed to condense conversation history: no summary generated."))
        return
    agent.display.emit(InfoEvent(message=f"Conversation history condensed. Summary:\n{summary}"))

    sys_msg = f"You are an assistant having a conversation with a user. Here is the summary of the conversation history so far:\n{summary}"
    agent.conversation.set_system_message_content(sys_msg)
    agent.conversation.messages += keep_messages
    return