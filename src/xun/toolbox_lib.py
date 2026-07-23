from __future__ import annotations
from dataclasses import dataclass
import json
from typing import (
    cast,
    Callable, Any,
    get_type_hints,
)
import inspect
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, ConfigDict, ValidationError, create_model

@dataclass(frozen=True)
class Function:
    func: Callable
    name: str
    description: str
    args_model: type[BaseModel]
    tool_schema: ChatCompletionToolParam

    @staticmethod
    def from_function(func: Callable) -> Function:
        name = func.__name__
        description = func.__doc__ or ""
        args_model = _build_args_model_from_function(func)
        tool_param = ChatCompletionToolParam(
            type="function",
            function={
                "name": name,
                "description": description,
                "parameters": args_model.model_json_schema(),
            },
        )
        return Function(
            func=func,
            name=name,
            description=description,
            tool_schema=tool_param,
            args_model=args_model,
        )

    def call(self, args: str | dict[str, Any]) -> Any:
        """Invoke the wrapped function with OpenAI tool-call arguments."""
        if isinstance(args, str):
            raw = args.strip()
            if not raw:
                parsed_args: Any = {}
            else:
                try:
                    parsed_args = json.loads(raw)
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"Tool '{self.name}' arguments must be valid JSON: {e.msg}"
                    ) from e
        elif isinstance(args, dict):
            parsed_args = args
        else:
            raise TypeError(
                f"Tool '{self.name}' arguments must be a JSON string or dict, got {type(args).__name__}."
            )

        if not isinstance(parsed_args, dict):
            raise ValueError(
                f"Tool '{self.name}' arguments must decode to a JSON object, got {type(parsed_args).__name__}."
            )

        try:
            validated = self.args_model.model_validate(parsed_args, strict=True)
        except ValidationError as e:
            raise ValueError(f"Invalid arguments for tool '{self.name}': {e}") from e

        return self.func(**validated.model_dump())


def _build_args_model_from_function(func: Callable) -> type[BaseModel]:
    sig = inspect.signature(func)
    type_hints = get_type_hints(func)
    fields: dict[str, tuple[Any, Any]] = {}
    for name, param in sig.parameters.items():
        if name in ("self", "context"):
            continue
        if name in type_hints:
            param_type = type_hints[name]
        elif param.default is not inspect.Parameter.empty and param.default is not None:
            param_type = type(param.default)
        else:
            param_type = Any

        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[name] = (param_type, default)

    create_fields = cast(dict[str, Any], fields)
    return create_model(  # type: ignore[call-overload]
        f"ToolArgs_{func.__name__}",
        __config__=ConfigDict(extra="forbid"),
        **create_fields,
    )

if __name__ == "__main__":
    # Example usage
    def example_function(param1: str |bool, param2: int = 42) -> bool:
        """This is an example function."""
        return True

    wrapped = Function.from_function(example_function)
    print(wrapped.tool_schema["function"].get("parameters"))
    print(wrapped.call('{"param1": true}'))
