from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall

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