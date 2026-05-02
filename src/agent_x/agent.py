from openai import OpenAI
from typing import Any
import json
import json_repair
from pathlib import Path
from tempfile import TemporaryDirectory

from .conversation import Conversation
from .config import app_config
from .prompt import get_condense_prompt
from .toolbox import ToolBox, extract_tool_calls
from .context import global_context, ToolCallContext, tool_call_context, ExecutionContext, execution_context
from .render import Renderer, confirm

class Agent:
    def __init__(
        self, 
        name: str = "agent", 
        toolbox: ToolBox | None = None,
        openai_client: OpenAI | None = None, 
        persistent_store: Path | None = None,
        ):
        self.name = name
        self.app_config = app_config()

        if openai_client is None:
            openai_client = OpenAI(
                base_url = self.app_config.provider.openai_base_url,
                api_key = self.app_config.provider.openai_api_key,
            )
        
        if toolbox is None:
            toolbox = ToolBox()

        self.toolbox = toolbox
        self.openai_client = openai_client

        self.conversation = Conversation()
        self.renderer = Renderer(self)

        if persistent_store:
            if persistent_store.exists():
                assert persistent_store.is_dir(), f"Persistent store path {persistent_store} must be a directory."
                self.load(persistent_store)
            self.renderer.console.print(f"[bold green]Using persistent store from {persistent_store}[/bold green]")
        self.persistent_store = persistent_store

    def dump(self, store_dir: Path):
        if not store_dir.exists():
            store_dir.mkdir(exist_ok=True)
        conv_file = store_dir / f"conversation.json"
        self.conversation.dump(conv_file)
    
    def load(self, store_dir: Path):
        conv_file = store_dir / f"conversation.json"
        if conv_file.exists():
            self.conversation.load(conv_file)
        else:
            self.renderer.error(f"No conversation history found in {conv_file}. Starting with an empty conversation.")
    
    def _dump(self):
        if self.persistent_store:
            self.dump(self.persistent_store)
    
    def _execute(self, max_iterations: int = 64) -> str:
        if max_iterations <= 0:
            self.renderer.error("Maximum tool call iterations exceeded.")
            return "[Error: Maximum tool call iterations exceeded.]"

        _text = f"{self.name} running" + (f"(max remaining iterations: {max_iterations})" if max_iterations < 8 else "")
        with self.renderer.working_mgr(_text):
            n_max_retries = 5
            while True:
                try:
                    resp = self.openai_client.chat.completions.create(
                        model=self.app_config.provider.openai_model,
                        tools = self.toolbox.list_tools_json(),     # type: ignore
                        tool_choice="auto",
                        messages = self.conversation.messages, 
                        timeout = 600,
                    )
                    break

                except KeyboardInterrupt:
                    # remove last message if from user, to allow retry
                    if self.conversation.messages and self.conversation.messages[-1]["role"] == "user":
                        self.conversation.messages.pop()
                    self.renderer.error("Execution interrupted by user.")
                    return "[Error: Execution interrupted by user.]"

                except Exception as e:
                    self.renderer.error(f"Error during chat completion: {e}, retrying...")
                    if n_max_retries > 0 and confirm("Retry?", default=True):
                        n_max_retries -= 1
                        continue
                    else:
                        raise e

        choice = extract_tool_calls(resp.choices[0])

        if choice.message.content:
            self.renderer.render_model_message_content(choice.message.content)
        self.conversation.add_agent_message(choice.message)
        self._dump()

        __tool_called = False
        if choice.message.tool_calls:

            for tool_call in choice.message.tool_calls:
                if tool_call.type != "function":
                    self.renderer.error(f"Unsupported tool call type: {tool_call.type}")
                    continue

                tool_id = tool_call.id
                tool_name = tool_call.function.name
                arguments = tool_call.function.arguments

                try:
                    tool_call_context.set(ToolCallContext(agent=self,))
                    arguments_json: Any = json_repair.loads(arguments)
                    with self.renderer.tool_call_mgr(tool_id, tool_name, arguments_json):
                        res = self.toolbox.call_tool_json(tool_name, arguments_json)
                        tool_result = json.dumps(res if isinstance(res, dict) else res)
                except Exception as e:
                    tool_result = json.dumps({
                        "error": str(e),
                    })
                finally:
                    tool_call_context.set(None)

                self.conversation.add_tool_call(tool_id, tool_result)
                __tool_called = True
        
        if __tool_called:
            self._dump()
            return self._execute(max_iterations=max_iterations - 1)
        
        return choice.message.content or "[No content]"

    def execute(self, max_iterations: int = 64) -> str:
        with TemporaryDirectory(prefix=f"{self.name}_", delete=True) as temp_dir_path:
            global_context.lock().tempdirs[self.name] = Path(temp_dir_path)
            execution_context.set(ExecutionContext(
                agent=self, 
                tempdir=Path(temp_dir_path),
                ))
            try:
                return self._execute(max_iterations=max_iterations)
            finally:
                execution_context.set(None)
                del global_context.lock().tempdirs[self.name]
    
    def system(self, content: str):
        self.conversation.set_system_message_content(content)
        return self
    
    def instruct(self, instruction: str):
        self.conversation.add_user_instruct(instruction)
        return self
    
    def condense_conversation(self):
        _condense_conversation(self)

def _condense_conversation(agent: Agent):
    """
    Condense the conversation history of the agent by keeping only the last user message and the assistant messages after that. 
    """
    agent.renderer.console.print("[bold blue]Condensing conversation history...[/bold blue]")

    keep_messages = agent.conversation.pop_from_last_user_message()
    condense_messages = agent.conversation.messages
    
    if not condense_messages:
        # revert
        agent.conversation.messages = condense_messages + keep_messages
        return
    
    client = agent.openai_client
    condense_messages_json = json.dumps(condense_messages, indent=4)
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
        agent.renderer.error("Failed to condense conversation history: no summary generated.")
        return
    agent.renderer.console.print(f"[bold blue]Conversation history condensed. Summary:[/bold blue]\n{summary}")

    sys_msg = f"You are an assistant having a conversation with a user. Here is the summary of the conversation history so far:\n{summary}"
    agent.conversation.set_system_message_content(sys_msg)
    agent.conversation.messages += keep_messages
    return