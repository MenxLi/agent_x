from openai import OpenAI
from openai.types import chat
import json
from rich.prompt import Confirm
from .tool_utils import tool_to_openai_format, ToolCallClient, extract_tool_calls
from .render import Renderer

def get_docker_host_ip():
    import subprocess
    result = subprocess.run("ip route | grep default | awk '{print $3}'", shell=True, capture_output=True, text=True)
    return result.stdout.strip()

class AgentBase:
    def __init__(self, name: str = "agent", openai_client: OpenAI | None = None, mcp_client: ToolCallClient | None = None):
        self.name = name
        if openai_client is None:
            openai_client = OpenAI(
                base_url = f"http://{get_docker_host_ip()}:8000/v1",
            )
        
        if mcp_client is None:
            mcp_client = ToolCallClient()

        self.openai_client = openai_client
        self.mcp_client = mcp_client

        self.messages: list[chat.chat_completion_message_param.ChatCompletionMessageParam] = []
        self.renderer = Renderer(self)
    
    def _append_message(self, message: chat.chat_completion_message_param.ChatCompletionMessageParam):
        self.messages.append(message)
    
    def execute(self, max_iterations: int = 16):
        if max_iterations <= 0:
            self.renderer.error("Maximum tool call iterations exceeded.")
            return

        while True:
            try:
                _text = f"{self.name} working" + (f"(max remaining iterations: {max_iterations})" if max_iterations < 8 else "")
                with self.renderer.working_context(_text):
                    resp = self.openai_client.chat.completions.create(
                        model="/m/Qwen3.6-35B-A3B",
                        tools=[ tool_to_openai_format(tool) for tool in self.mcp_client.list_tools() ],  # type: ignore
                        tool_choice="auto",
                        messages = self.messages
                    )
                break
            except Exception as e:
                self.renderer.error(f"Error during chat completion: {e}")
                Confirm.ask("Retry?", default=True)

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
                        res = self.mcp_client.call_tool(tool_name, json.loads(arguments))
                        tool_result = json.dumps(res.structured_content if isinstance(res.structured_content, dict) else res.structured_content)
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
    
    def instruct(self, instruction: str):
        self._append_message({
            "role": "user",
            "content": instruction,
        })