from openai.types import chat
import json
from .tool_utils import tool_to_openai_format, ToolCallClient, extract_tool_calls

def get_docker_host_ip():
    import subprocess
    result = subprocess.run("ip route | grep default | awk '{print $3}'", shell=True, capture_output=True, text=True)
    return result.stdout.strip()

from openai import OpenAI

mcp_client = ToolCallClient()
client = OpenAI(
    base_url = f"http://{get_docker_host_ip()}:8000/v1",
    api_key="KNr9qjwWf3uZa_5LUtJvVg", 
)

messages: list[chat.chat_completion_message_param.ChatCompletionMessageParam] = [
    {
        "role": "user",
        "content": "What's in the current directory? You can use the fs_list tool to find out."
    }
]

resp = client.chat.completions.create(
    model="/m/Qwen3.6-35B-A3B-FP8",
    tools=[ tool_to_openai_format(tool) for tool in mcp_client.list_tools() ],  # type: ignore
    tool_choice="auto",
    messages = messages
)

choice = extract_tool_calls(resp.choices[0])

# run the extracted tool calls
if choice.message.tool_calls:
    for tool_call in choice.message.tool_calls:
        if tool_call.type != "function":
            print(f"Unsupported tool call type: {tool_call.type}")
            continue
        tool_name = tool_call.function.name
        arguments = tool_call.function.arguments
        print(f"Running tool: {tool_name} with arguments: {arguments}")

        res = mcp_client.call_tool(tool_name, json.loads(arguments))
        messages.append({
            "role": "tool", 
            "name": tool_name,
            "content": json.dumps(res.structured_content if isinstance(res.structured_content, dict) else res.structured_content),
        })  # type: ignore
        
resp2 = client.chat.completions.create(
    model="/m/Qwen3.6-35B-A3B-FP8",
    tools=[ tool_to_openai_format(tool) for tool in mcp_client.list_tools() ],  # type: ignore
    tool_choice="auto",
    messages = messages
)

choice2 = extract_tool_calls(resp2.choices[0])
print(choice2.message.content)