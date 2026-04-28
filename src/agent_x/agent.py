from openai import OpenAI
from openai.types import chat
import json
from rich.prompt import Confirm
from .config import app_config
from .toolbox import ToolBox, extract_tool_calls
from .render import Renderer

class Agent:
    def __init__(
        self, 
        name: str = "agent", 
        toolbox: ToolBox | None = None,
        openai_client: OpenAI | None = None, 
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

        self.messages: list[chat.chat_completion_message_param.ChatCompletionMessageParam] = []
        self.renderer = Renderer(self)
    
    def _append_message(self, message: chat.chat_completion_message_param.ChatCompletionMessageParam):
        self.messages.append(message)
    
    def clear_last_n_messages(self, n: int):
        """ Clear the last n messages in the conversation history.  """
        if n <= 0:
            return
        self.messages = self.messages[:-n]
    
    def pop_last_user_message(self) -> str:
        """
        Pop the last user message in the conversation history and return the content of the popped message.
        If there is no user message, raise an error.
        Can be used when we want to change the instruction and let the agent try again.
        """
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i]["role"] == "user":
                content = self.messages.pop(i)
                assert content and "content" in content and isinstance(content["content"], str), "The popped user message has no content or the content is not a string."
                return content["content"]
        raise RuntimeError("No user message found in conversation history.")
    
    def execute(self, max_iterations: int = 16):
        if max_iterations <= 0:
            self.renderer.error("Maximum tool call iterations exceeded.")
            return

        _text = f"{self.name} working" + (f"(max remaining iterations: {max_iterations})" if max_iterations < 8 else "")
        with self.renderer.working_context(_text):
            while True:
                try:
                    resp = self.openai_client.chat.completions.create(
                        model=self.app_config.provider.openai_model,
                        tools = self.toolbox.list_tools_json(),     # type: ignore
                        tool_choice="auto",
                        messages = self.messages, 
                        timeout = 300,
                    )
                    break

                except KeyboardInterrupt:
                    self.renderer.error("Execution interrupted by user.")
                    return

                except Exception as e:
                    self.renderer.error(f"Error during chat completion: {e}")
                    if Confirm.ask("Retry?", default=True):
                        continue
                    else:
                        raise e

        choice = extract_tool_calls(resp.choices[0])

        if choice.message.tool_calls:
            if choice.message.content and choice.message.content.strip() != "":
                self.renderer.render_model_message(choice.message.content)

            self._append_message({
                "role": "assistant",
                "content": choice.message.content,
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                    for tool_call in choice.message.tool_calls
                    if tool_call.type == "function"
                ],
            })  # type: ignore
        elif choice.message.content and choice.message.content.strip() != "":
            self.renderer.render_model_message(choice.message.content)
            self._append_message({
                "role": "assistant",
                "content": choice.message.content,
            })

        __tool_called = False
        if choice.message.tool_calls:

            for tool_call in choice.message.tool_calls:
                if tool_call.type != "function":
                    self.renderer.error(f"Unsupported tool call type: {tool_call.type}")
                    continue

                tool_name = tool_call.function.name
                arguments = tool_call.function.arguments

                with self.renderer.tool_call_context(tool_name, json.loads(arguments)):
                    try:
                        res = self.toolbox.call_tool_json(tool_name, json.loads(arguments))
                        tool_result = json.dumps(res if isinstance(res, dict) else res)
                    except Exception as e:
                        tool_result = json.dumps({
                            "error": str(e),
                        })
                        self.renderer.error(f"Error calling tool {tool_name}: {e}")

                self._append_message({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result,
                })  # type: ignore
                __tool_called = True
        
        if __tool_called:
            self.execute(max_iterations=max_iterations - 1)
        
        return choice.message.content or ""
    
    def instruct(self, instruction: str):
        self._append_message({
            "role": "user",
            "content": instruction,
        })