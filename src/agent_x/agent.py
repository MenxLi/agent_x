from openai import OpenAI
from openai.types import chat
from pathlib import Path
import json, time
import string
from .config import app_config, confirm
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
    
    def dump_conversation(self, file_path: str | Path):
        """ Dump the conversation history to a json file. """
        with open(file_path, "w") as f:
            json.dump({
                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "messages": self.messages,
            }, f, indent=2)
    
    def load_conversation(self, file_path: str | Path):
        """ Load the conversation history from a json file. """
        with open(file_path, "r") as f:
            self.messages = json.load(f)['messages']
    
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
                    # remove last message if from user, to allow retry
                    if self.messages and self.messages[-1]["role"] == "user":
                        self.messages.pop()
                    self.renderer.error("Execution interrupted by user.")
                    return

                except Exception as e:
                    self.renderer.error(f"Error during chat completion: {e}")
                    if confirm("Retry?", default=True):
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

                tool_id = tool_call.id
                tool_name = tool_call.function.name
                arguments = tool_call.function.arguments

                try:
                    with self.renderer.tool_call_context(tool_id, tool_name, json.loads(arguments)):
                        res = self.toolbox.call_tool_json(tool_name, json.loads(arguments))
                        tool_result = json.dumps(res if isinstance(res, dict) else res)
                except Exception as e:
                    tool_result = json.dumps({
                        "error": str(e),
                    })

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
        return self
    
    def condense_conversation(self):
        _condense_conversation(self)

__condense_prompt = string.Template("""
You are a conversation memory manager. Condense the chat history below into a compact, structured summary that preserves all critical context for seamless continuation.
Your output will be used as a system message to inform the assistant of the conversation history, so it should be concise yet comprehensive enough for the assistant to understand the context and continue the conversation without losing important information.

RULES:
- PRESERVE: user goals, explicit preferences, factual claims, decisions made, pending tasks, open questions, and any constraints or rules established.
- DISCARD: greetings, small talk, filler, repeated statements, and conversational noise.
- GROUP by topic if it improves clarity, but maintain logical flow.
- Keep total output under 1024 tokens. If uncertain about a detail, mark it as "unconfirmed".
- OUTPUT in markdown format with the following field, do not add any other extra comment or explanation:

SCHEMA (in markdown format):
- overview: 1-2 sentence high-level summary of conversation purpose & current state
- key_facts: list of important facts mentioned
- user_preferences: list of user preferences
- decisions: list of decisions made
- pending_tasks: list of pending tasks
- open_questions: list of open questions
- tone_context: brief note on communication style or constraints (e.g., "formal", "prefers bullet points", "avoid technical jargon")

CHAT HISTORY:
$chat_history
""")
def _condense_conversation(agent: Agent):
    """
    Condense the conversation history of the agent by keeping only the last user message and the assistant messages after that. 
    """
    agent.renderer.console.print("[bold blue]Condensing conversation history...[/bold blue]")

    condense_messages = []
    keep_messages = []
    for i in range(len(agent.messages) - 1, -1, -1):
        if agent.messages[i]["role"] == "user":
            condense_messages = agent.messages[:i]
            keep_messages = agent.messages[i:]
            break
    
    if not condense_messages:
        return
    
    client = agent.openai_client
    condense_messages_json = json.dumps(condense_messages, indent=4)
    resp = client.chat.completions.create(
        model=agent.app_config.provider.openai_model,
        messages = [
            {
                "role": "user",
                "content": __condense_prompt.substitute({
                    "chat_history": condense_messages_json,
                }),
            },
        ],
        timeout = 300,
    )
    summary = resp.choices[0].message.content
    if summary is None:
        agent.renderer.error("Failed to condense conversation history: no summary generated.")
        return
    agent.renderer.console.print(f"[bold blue]Conversation history condensed. Summary:[/bold blue]\n{summary}")

    # insert the summary as a system message before the first user message
    new_system_message = "You are an assistant having a conversation with a user. Here is the summary of the conversation history so far:\n" + summary
    agent.messages = [
        {
            "role": "system",
            "content": new_system_message,
        },
    ] + keep_messages   # type: ignore
    return