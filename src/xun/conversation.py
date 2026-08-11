from openai.types import chat
from typing import Any, Sequence, cast
from typing_extensions import TypedDict
from pathlib import Path
import uuid, json, time
from PIL.Image import Image
import jinja2
import markdown
from markupsafe import Markup, escape
from .toolbox import ToolResultType
from .util import image_to_url


MAX_HISTORY_CONTENT_LENGTH = 1000
def _remove_empty_tool_calls(message: Any) -> Any:
    # some provider does not allow empty list for tool_calls
    if not isinstance(message, dict):
        return message

    sanitized = dict(message)
    if sanitized.get("tool_calls") == []:
        sanitized.pop("tool_calls", None)
    return sanitized


def _expand_json_content(content: Any) -> Any:
    if not isinstance(content, str):
        return content

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return content

    return parsed if isinstance(parsed, (dict, list)) else content


class Conversation:
    class MessageRecord(TypedDict):
        role: str
        content: str

    def __init__(self):
        self.messages: list[chat.chat_completion_message_param.ChatCompletionMessageParam] = []
        self.conversation_id: str = uuid.uuid4().hex
    
    def clear(self):
        self.messages.clear()

    def to_json(self) -> dict:
        return {
            "conversation_id": self.conversation_id,
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "messages": self.messages,
        }
    
    def dumps(self) -> str:
        return json.dumps(self.to_json(), indent=2, ensure_ascii=False)
    
    def dump(self, file_path: str | Path):
        with open(file_path, "w") as f:
            return f.write(self.dumps())
    
    def load_json(self, data: dict):
        self.conversation_id = data.get("conversation_id", self.conversation_id)
        self.messages = [_remove_empty_tool_calls(msg) for msg in data.get("messages", [])]
    
    def loads(self, data: str):
        obj = json.loads(data)
        self.load_json(obj)
    
    def load(self, file_path: str | Path):
        with open(file_path, "r") as f:
            self.loads(f.read())
    
    def set_system_message_content(self, content: str):
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0]["content"] = content
        else:
            self.messages.insert(0, {"role": "system", "content": content})

    @staticmethod
    def content_to_text(content: Any, truncate: bool = False) -> str:
        if isinstance(content, str):
            text = content
        else:
            text = json.dumps(content, indent=4)

        if truncate and len(text) > MAX_HISTORY_CONTENT_LENGTH:
            return text[:MAX_HISTORY_CONTENT_LENGTH] + "...(truncated)"
        return text

    @classmethod
    def content_to_html(cls, content: Any) -> Markup:
        def render_text(text: str) -> Markup:
            return Markup(markdown.markdown(
                str(escape(text)),
                extensions=["fenced_code", "tables"],
            ))

        if not isinstance(content, list):
            return render_text(cls.content_to_text(content))

        parts: list[Markup] = []
        for item in content:
            if not isinstance(item, dict):
                parts.append(render_text(cls.content_to_text(item)))
                continue

            if item.get("type") == "text":
                parts.append(render_text(str(item.get("text", ""))))
                continue

            image_url = item.get("image_url", {}).get("url") if isinstance(item.get("image_url"), dict) else None
            if item.get("type") == "image_url" and isinstance(image_url, str):
                parts.append(Markup(
                    '<figure class="message-image"><img src="{}" alt="User-provided image" loading="lazy"></figure>'
                ).format(escape(image_url)))
                continue

            parts.append(render_text(cls.content_to_text(item)))

        return Markup("\n").join(parts)
    
    def append_user_message(self, extra_content: str ):
        if not self.messages or self.messages[-1].get("role") != "user":
            raise ValueError("No user message to append to. Please add a user message first.")

        last_message = self.messages[-1]
        last_content = last_message.get("content", "")
        if isinstance(last_content, str):
            last_message["content"] = last_content + extra_content
        elif isinstance(last_content, list):
            for item in last_content:
                if isinstance(item, dict) and item.get("type") == "text":
                    assert "text" in item, "Text content missing in user message part."
                    item["text"] = item.get("text", "") + extra_content
                    break
        else:
            raise ValueError(f"Unexpected content type in last user message: {type(last_content)}")

    def add_user_message(
        self,
        content: str,
        images: Sequence[str | Image] | None = None,
    ) -> None:
        normalized_images = [image_to_url(image) for image in images or ()]
        user_content: str | list[dict[str, Any]]
        if not normalized_images:
            user_content = content
        else:
            parts: list[dict[str, Any]] = []
            if content:
                parts.append({"type": "text", "text": content})
            parts.extend({
                "type": "image_url", 
                "image_url": {"url": image}
                } for image in normalized_images)
            user_content = parts

        self.messages.append(cast(chat.ChatCompletionUserMessageParam, {"role": "user", "content": user_content}))
    
    def add_agent_message(self, msg: chat.chat_completion_message.ChatCompletionMessage):
        self.messages.append(_remove_empty_tool_calls(msg.to_dict()))     # type: ignore
    
    def add_tool_call(self, tool_call_id: str, content: ToolResultType):
        """ Add tool call result, the tool call is recorded via assistant message """
        try:
            content_str = content.value_str()
        except Exception as e:
            content_str = f"[Error] Failed to serialize tool result: {str(e)}"
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content_str
        })

    def pop_last_message_if_user(self) -> dict[str, Any] | None:
        if not self.messages or self.messages[-1].get("role") != "user":
            return None
        return cast(dict[str, Any], self.messages.pop())
    
    def pop_from_last_user_message(self, inclusive: bool = True) -> list[Any]:
        """
        inclusive=True: pop the last user message as well as afterwards
        inclusive=False: keep the last user message, pop afterwards
        """
        for i in range(len(self.messages)-1, -1, -1):
            if self.messages[i]["role"] == "user":
                old = self.messages
                if inclusive:
                    self.messages = self.messages[:i]
                    return old[i:]
                else:
                    if i == len(self.messages) - 1:
                        return []
                    self.messages = self.messages[:i+1]
                    return old[i+1:]
        return []
    
    def to_history(self, truncate = False) -> list[MessageRecord]:
        res = []
        for msg in self.messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            res.append(self.MessageRecord(
                role=role,
                content=self.content_to_text(content, truncate=truncate),
            ))
        return res

    def render_history_as_html(self) -> str:
        messages = []
        message_number = 0
        for message in self.messages:
            role = message.get("role", "unknown")
            tool_details = None
            tool_label = None
            if role == "tool":
                tool_details = {
                    "tool_call_id": message.get("tool_call_id"),
                    "content": _expand_json_content(message.get("content")),
                }
                tool_label = "Tool result"
            elif message.get("tool_calls"):
                tool_details = message.get("tool_calls")
                functions = [call.get("function", {}).get("name") for call in tool_details or []]
                tool_label = ", ".join(name for name in functions if name) or "Tool call"

            message_id = None
            message_hash = None
            if role in {"user", "assistant"} and tool_details is None:
                message_number += 1
                message_id = f"message-{message_number}"
                message_hash = f"#{message_number}"

            messages.append({
                "role": role,
                "content": self.content_to_html(message.get("content", "")),
                "tool_details": tool_details,
                "tool_label": tool_label,
                "message_id": message_id,
                "message_hash": message_hash,
            })

        template_path = Path(__file__).with_name("assets") / "conversation.template.html"
        environment = jinja2.Environment(autoescape=True)
        environment.policies["json.dumps_kwargs"] = {"ensure_ascii": False}
        return environment.from_string(template_path.read_text(encoding="utf-8")).render(messages=messages)
