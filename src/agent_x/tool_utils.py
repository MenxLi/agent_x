import mcp
from openai.types import chat
from fastmcp import Client
import asyncio
from ._toolcall_fix import extract_tool_calls_from_text
from .g import global_context

def tool_to_openai_format(tool: mcp.types.Tool):
    schema = tool.inputSchema
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": schema
        }
    }

class ToolCallClient:
    def __init__(self):
        self.client = Client(global_context().mcp)

    def call_tool(self, tool_name: str, arguments: dict):
        async def _call_tool():
            async with self.client:
                return await self.client.call_tool(
                    name=tool_name,
                    arguments=arguments,
                )
        return asyncio.run(_call_tool())
    
    def list_tools(self):
        async def _list_tools():
            async with self.client:
                return await self.client.list_tools()
        return asyncio.run(_list_tools())

def extract_tool_calls(choice: chat.chat_completion.Choice) -> chat.chat_completion.Choice:
    if choice.message.tool_calls:
        return choice

    # https://github.com/vllm-project/vllm/issues/39056
    # https://github.com/vllm-project/vllm/issues/29192

    content = choice.message.content
    if content is None:
        return choice

    cleaned, tool_calls = extract_tool_calls_from_text(content)

    choice.message.content = cleaned
    # dict to list of ToolCall
    tool_calls_typed: list[chat.chat_completion_message_function_tool_call.ChatCompletionMessageFunctionToolCall] = []
    for tc in tool_calls:
        tool_calls_typed.append(
            chat.chat_completion_message_function_tool_call.ChatCompletionMessageFunctionToolCall(
                id=tc["id"],
                type="function",
                function=chat.chat_completion_message_function_tool_call.Function(
                    name=tc["function"]["name"],
                    arguments=tc["function"]["arguments"],
                ),
            )
        )
    
    choice.message.tool_calls = tool_calls_typed    # type: ignore
    return choice

