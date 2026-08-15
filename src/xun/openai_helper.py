from typing import Optional
from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall
from openai.types.chat.chat_completion_message import ChatCompletionMessage

class ChatCompletionMessageWithReasoning(ChatCompletionMessage):
    """
    My hack to add reasoning field to the model...

    By default the OpenAI API does not support reasoning field, 
    but some models require `preserve_thinking` to be set to true, 
    and need the reasoning field to be present in the request...

    To validate this works:
    https://www.reddit.com/r/LocalLLaMA/comments/1sne4gh/psa_qwen36_ships_with_preserve_thinking_make_sure/

    Note the field name may be different for different providers, 
    `reasoning` is used by vllm.
    """
    reasoning: Optional[str]


def accumulate_tool_calls(
    deltas: list[ChoiceDeltaToolCall],
 ) -> list[ChatCompletionMessageToolCall]:
    """Accumulate streamed tool-call deltas into complete tool calls."""

    calls: dict[int, dict] = {}

    for delta in deltas:
        index = delta.index

        call = calls.setdefault(
            index,
            {
                "id": None,
                "type": "function",
                "function": {
                    "name": "",
                    "arguments": "",
                },
            },
        )

        if delta.id is not None:
            call["id"] = delta.id

        if delta.type is not None:
            call["type"] = delta.type
            assert call["type"] == "function", f"Unsupported tool call type: {call['type']}"

        if delta.function is not None:
            if delta.function.name is not None:
                call["function"]["name"] += delta.function.name

            if delta.function.arguments is not None:
                call["function"]["arguments"] += delta.function.arguments

    return [
        ChatCompletionMessageToolCall.model_validate(call)
        for _, call in sorted(calls.items())
    ]