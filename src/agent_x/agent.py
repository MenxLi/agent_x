from openai import OpenAI
from typing import Any
import json
import json_repair
import string
from .conversation import Conversation
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

        self.conversation = Conversation()
        self.renderer = Renderer(self)
    
    def execute(self, max_iterations: int = 16) -> str:
        if max_iterations <= 0:
            self.renderer.error("Maximum tool call iterations exceeded.")
            return "[Error: Maximum tool call iterations exceeded.]"

        _text = f"{self.name} working" + (f"(max remaining iterations: {max_iterations})" if max_iterations < 8 else "")
        with self.renderer.working_context(_text):
            n_max_retries = 5
            while True:
                try:
                    resp = self.openai_client.chat.completions.create(
                        model=self.app_config.provider.openai_model,
                        tools = self.toolbox.list_tools_json(),     # type: ignore
                        tool_choice="auto",
                        messages = self.conversation.messages, 
                        timeout = 300,
                    )
                    break

                except KeyboardInterrupt:
                    # remove last message if from user, to allow retry
                    if self.conversation.messages and self.conversation.messages[-1]["role"] == "user":
                        self.conversation.messages.pop()
                    self.renderer.error("Execution interrupted by user.")
                    return "[Error: Execution interrupted by user.]"

                except Exception as e:
                    self.renderer.error(f"Error during chat completion: {e}")
                    if n_max_retries > 0 and confirm("Retry?", default=True):
                        n_max_retries -= 1
                        continue
                    else:
                        raise e

        choice = extract_tool_calls(resp.choices[0])

        if choice.message.content:
            self.renderer.render_model_message_content(choice.message.content)
        self.conversation.add_agent_message(choice.message)

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
                    arguments_json: Any = json_repair.loads(arguments)
                    with self.renderer.tool_call_context(tool_id, tool_name, arguments_json):
                        res = self.toolbox.call_tool_json(tool_name, arguments_json)
                        tool_result = json.dumps(res if isinstance(res, dict) else res)
                except Exception as e:
                    tool_result = json.dumps({
                        "error": str(e),
                    })

                self.conversation.add_tool_call(tool_id, tool_result)
                __tool_called = True
        
        if __tool_called:
            self.execute(max_iterations=max_iterations - 1)
        
        return choice.message.content or "[No content]"
    
    def instruct(self, instruction: str):
        self.conversation.add_user_instruct(instruction)
        return self
    
    def condense_conversation(self):
        _condense_conversation(self)

__condense_prompt = string.Template("""
You are a conversation memory manager. Condense the chat history below into a compact, structured summary that preserves all critical context for seamless continuation.
Your output will be used as a system message to inform the assistant of the conversation history, so it should be concise yet comprehensive enough for the assistant to understand the context and continue the conversation without losing important information.

RULES:
- PRESERVE SYSTEM MESSAGES: If any `system` role messages exist in the history, extract and include their key instructions/constraints in the "System Context" section. 
- PRESERVE: user goals, explicit preferences, factual claims, decisions made, pending tasks, open questions, and any constraints or rules established.
- DISCARD: greetings, small talk, filler, repeated statements, and conversational noise.
- GROUP by topic if it improves clarity, but maintain logical flow.
- Keep total output under 1024 tokens. If uncertain about a detail, mark it as "unconfirmed".
- OUTPUT in markdown format with the following field, do not add any other extra comment or explanation:

SCHEMA (in markdown format):
- system_context: key instructions or constraints from system messages (if any)
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

    sys_msg = f"You are an assistant having a conversation with a user. Here is the summary of the conversation history so far:\n{summary}"
    agent.conversation.set_system_message_content(sys_msg)
    agent.conversation.messages += keep_messages
    return