from typing import Any, Sequence, Optional, overload
from dataclasses import dataclass, field
from pathlib import Path
import json
import uuid
import weakref

import json_repair
from openai import OpenAI
from pydantic import BaseModel
from PIL.Image import Image
from threading import Semaphore, Event
from contextlib import contextmanager

from .display_abstract import *
from .display import Display
from .conversation import Conversation
from .config import app_config
from .prompt import get_condense_prompt
from .error_catch import except_safe, Result, ErrorInfo
from .toolbox import ToolBox, extract_tool_calls
from .tempdir import DeferredTempDirectory
from .context import ExecutionContext, execution_context
from .command import CommandRegistry
from .hooks import Hooks, HookArgs
from .types import ToolResultType, CancelledError

def _default_openai_client():
    config = app_config()
    return OpenAI(
        base_url = config.provider.openai_base_url,
        api_key = config.provider.openai_api_key,
    )

DEFAULT_MAX_ITERATIONS = 64
DEFAULT_API_CALL_LIMIT = 3

@dataclass
class Agent:
    name: str = field(default_factory=lambda: f"agent-{str(uuid.uuid4())[:8]}")
    identifier: str = field(default_factory=lambda: str(uuid.uuid4()))
    display: DisplayAbstract = field(default_factory=Display)
    conversation: Conversation = field(default_factory=Conversation)
    toolbox: ToolBox = field(default_factory=ToolBox)
    command: CommandRegistry = field(default_factory=CommandRegistry)
    openai_client: OpenAI = field(default_factory=_default_openai_client)
    workdir: Path = field(default_factory=lambda: Path.cwd())
    tempdir: DeferredTempDirectory = field(default_factory=DeferredTempDirectory)
    persistent_store: Optional[Path] = None

    # below auto inherit
    api_call_semaphore: Semaphore = field(default_factory=lambda: Semaphore(DEFAULT_API_CALL_LIMIT))

    # below does not inherit
    state: dict[str, Any] = field(default_factory=dict)
    hooks: Hooks = field(default_factory=Hooks)
    _cancel_event: Event = field(default_factory=Event)

    def __post_init__(self):
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
        
        weakref.finalize(self, Agent._finalize, self)
        self.hooks.after_initialize.invoke(HookArgs.AfterInitializeArgs(agent=self))
    
    @property
    def app_config(self):
        return app_config()
    
    @staticmethod
    def inherit(
        parent_agent: "Agent", 
        share_tempdir: bool = True,
        share_display: bool = True,
        copy_toolbox: bool = True,
        copy_conversation: bool = False,
        copy_command: bool = True,
        persistent_store: Optional[Path] = None, 
        ) -> "Agent":
        """
        Create a new agent that inherits the configuration and state from the parent agent.
        """
        new_agent = Agent(
            name=f"{parent_agent.name}-child-{str(uuid.uuid4())[:8]}",
            display=parent_agent.display if share_display else Display(),
            tempdir=parent_agent.tempdir if share_tempdir else DeferredTempDirectory(),
            toolbox=parent_agent.toolbox.clone() if copy_toolbox else ToolBox(),
            command=parent_agent.command if copy_command else CommandRegistry(),
            openai_client=parent_agent.openai_client,
            persistent_store=persistent_store,

            # auto inherit
            api_call_semaphore=parent_agent.api_call_semaphore,
        )
        if copy_conversation:
            new_agent.conversation.messages = parent_agent.conversation.messages.copy()
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
        self._cancel_event.set()

    def check_cancel(self):
        if self._cancel_event.is_set():
            raise CancelledError("Operation cancelled by user.")

    @contextmanager
    def _cancellable_execution(self):
        try:
            yield
        except CancelledError:
            self.display.emit(ErrorEvent(message="Execution cancelled by user."))
            raise
        finally:
            self._cancel_event.clear()
    
    def _execute(self, call_id: str, context: Any) -> tuple[bool, str]:
        n_completion_max_retries = 3
        while True:
            self.check_cancel()
            try:
                params = {
                    "model": self.app_config.provider.openai_model,
                    "messages": self.conversation.messages,
                    "timeout": 3000,
                }
                if (tools_json := self.toolbox.list_tools_json(self.app_config.provider.model_capabilities)) and len(tools_json) > 0:
                    params["tools"] = tools_json
                    params["tool_choice"] = "auto"

                with self.api_call_semaphore:
                    resp = self.openai_client.chat.completions.create(**params)
                self.check_cancel()

                break

            except CancelledError:
                raise
            except KeyboardInterrupt:
                # remove last message if from user, to allow retry
                self.conversation.pop_last_message_if_user()
                self.display.emit(ErrorEvent(message="Execution interrupted by user."))
                return False, "[Error: Execution interrupted by user.]"

            except Exception as e:
                self.display.emit(ErrorEvent(message=f"Error during chat completion: {e}"))
                if n_completion_max_retries > 0 and self.display.get_confirm("Retry?", default=True):
                    n_completion_max_retries -= 1
                    continue
                else:
                    raise e

        choice = extract_tool_calls(resp.choices[0])

        if choice.message.content:
            self.display.emit(ModelMessageEvent(model_call_id=call_id, content=choice.message.content))
        self.conversation.add_agent_message(choice.message)
        self.dump()

        __tool_called = False

        if choice.message.tool_calls:
            tool_calls = [tool_call for tool_call in choice.message.tool_calls if tool_call.type == "function"]

            self.hooks.before_tool_call.invoke(HookArgs.BeforeToolCallArgs(
                agent=self,
                tool_calls=tool_calls
            ))
            tool_results: list[tuple[str, ToolResultType]] = []

            for tool_call in tool_calls:
                self.check_cancel()
                tool_id = tool_call.id
                tool_name = tool_call.function.name
                arguments = tool_call.function.arguments

                try:
                    arguments_json: Any = json_repair.loads(arguments)
                    self.display.emit(ToolCallEvent(tool_call_id=tool_id, tool_name=tool_name, args=arguments_json))
                    tool_res = self.toolbox.call_tool(
                        agent=self,
                        tool_name = tool_name, 
                        arguments = arguments_json, 
                        context = context
                        )
                    if tool_res.is_ok():
                        self.display.emit(ToolResultEvent(tool_call_id=tool_id, result=tool_res.value_json()))
                    else:
                        self.display.warning(f"Tool {tool_name} failed: {tool_res.unwrap_err().error}")
                except CancelledError:
                    raise
                except Exception as e:
                    self.display.error(f"Tool pipeline {tool_name} failed: {e}")
                    tool_res: ToolResultType = Result.Err(ErrorInfo(error="Tool pipeline failed", details=str(e)))

                tool_results.append((tool_id, tool_res))
                __tool_called = True
            
            self.hooks.after_tool_call.invoke(HookArgs.AfterToolCallArgs(
                agent=self,
                tool_results=tool_results
            ))
            for tool_id, tr in tool_results:
                self.conversation.add_tool_call(tool_id, tr)
        
        if __tool_called:
            self.dump()
        
        return __tool_called, choice.message.content or "[No content]"
    
    @overload
    @except_safe
    def execute[T: BaseModel](
        self, schema: type[T], 
        max_iterations: int = DEFAULT_MAX_ITERATIONS, 
        context: Any = None
    ) -> T: ...
    @overload
    @except_safe
    def execute(
        self, schema: None = None, 
        max_iterations: int = DEFAULT_MAX_ITERATIONS, 
        context: Any = None
    ) -> str: ...
    @except_safe
    def execute(
        self, schema: Optional[type[BaseModel]] = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        context: Any = None
        ):

        if schema is not None:
            self.conversation.append_user_message(
                "\n---\n"
                "Please respond in JSON format without any additional text. "
                "The JSON should conform to the following schema:\n"
                f"{schema.model_json_schema()}\n"
            )

        with Agent.context_agent(self), self._cancellable_execution():
            for iteration in range(max_iterations):
                self.check_cancel()
                model_call_id = str(uuid.uuid4())
                self.display.emit(ModelWorkingEvent(
                    model_call_id=model_call_id, 
                    remaining_iterations=max_iterations - iteration
                    ))
                should_continue, result = self._execute(model_call_id, context=context)
                if not should_continue:
                    if schema is not None:
                        try:
                            res_object = json_repair.loads(result)
                            return schema.model_validate(res_object)
                        except Exception as e:
                            self.display.emit(ErrorEvent(message=f"Failed to parse result into {schema}: {e}"))
                            raise e
                    else:
                        return result

            self.display.emit(ErrorEvent(message="Maximum tool call iterations exceeded."))
            raise RuntimeError("Maximum tool call iterations exceeded.")
    
    def system(self, content: str):
        self.conversation.set_system_message_content(content)
        return self
    
    def instruct(
        self, 
        instruction: str, 
        images: Sequence[str | Image] | None = None, 
        _emit_event: bool = True
        ):
        self.conversation.add_user_message(instruction, images=images)
        if _emit_event:
            with Agent.context_agent(self):
                self.display.emit(UserMessageEvent.from_inputs(instruction, images=images))
        return self
    
    def execute_command(self, command_name: str, arguments: Optional[str] = None):
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
    
    def condense_conversation(self):
        _condense_conversation(self)
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        self.finalize()
    
    def finalize(self):
        self._finalize(self)

    @staticmethod
    def _finalize(agent: "Agent"):
        if hasattr(agent, "__finalized") and getattr(agent, "__finalized"):
            return
        with Agent.context_agent(agent):
            agent.hooks.before_finalize.invoke(HookArgs.BeforeFinalizeArgs(agent=agent))
            agent.display.unbind(agent)
            agent.display.emit(AgentUnbindEvent())
        setattr(agent, "__finalized", True)
    
    @contextmanager
    @staticmethod
    def context_agent(agent: "Agent"):
        prev_context = execution_context.get()
        execution_context.set(ExecutionContext(agent=agent))
        try:
            yield
        finally:
            execution_context.set(prev_context)


def _condense_conversation(agent: Agent):
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