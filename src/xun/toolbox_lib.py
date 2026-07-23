from __future__ import annotations
from dataclasses import dataclass
import json
from typing import (
    TypeVar, Type, Generic, 
    Optional, Callable, Any,
    get_type_hints, 
    Union, TypedDict,
    get_origin,
    get_args,
    )
from types import UnionType
import inspect
from openai.types.chat import ChatCompletionToolParam

@dataclass(frozen=True)
class Function:
    func: Callable
    schema: FunctionSchema
    tool_param: ChatCompletionToolParam

    @staticmethod
    def from_function(func: Callable) -> Function:
        schema = function_schema(func)
        tool_param = function_schema_to_openai_completion_tool_schema(schema)
        return Function(func=func, schema=schema, tool_param=tool_param)

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
                        f"Tool '{self.schema.name}' arguments must be valid JSON: {e.msg}"
                    ) from e
        elif isinstance(args, dict):
            parsed_args = args
        else:
            raise TypeError(
                f"Tool '{self.schema.name}' arguments must be a JSON string or dict, got {type(args).__name__}."
            )

        if not isinstance(parsed_args, dict):
            raise ValueError(
                f"Tool '{self.schema.name}' arguments must decode to a JSON object, got {type(parsed_args).__name__}."
            )

        kwargs = dict(parsed_args)
        try:
            return self.func(**kwargs)
        except TypeError as e:
            raise ValueError(f"Invalid arguments for tool '{self.schema.name}': {e}") from e

@dataclass
class FunctionSchema:
    name: str
    description: str
    parameters: list[FunctionParam]
    return_type: Type

T = TypeVar("T")
@dataclass
class FunctionParam(Generic[T]):
    class _Empty: pass
    name: str
    type_hint: Type[T]
    default: T | _Empty = _Empty()

def function_schema(func: Callable):
    """Generate a tool schema for a given function."""
    sig = inspect.signature(func)
    function_name = func.__name__
    function_description = func.__doc__ or ""

    type_hints = get_type_hints(func)
    params = []
    for name, param in sig.parameters.items():
        if name in ("self", "context"):
            continue  # framework-injected parameters are not exposed to the model
        if not name in type_hints:
            raise ValueError(f"Type hint for parameter '{name}' is missing in function '{function_name}'.")
        param_type = type_hints[name]

        default_value = param.default if param.default is not inspect.Parameter.empty else FunctionParam._Empty()
        params.append(FunctionParam(name=name, type_hint=param_type, default=default_value))
    if not 'return' in type_hints:
        raise ValueError(f"Return type hint is missing in function '{function_name}'.")
    return_type = type_hints['return']

    return FunctionSchema(
        name=function_name, 
        description=function_description, 
        parameters=params, 
        return_type=return_type
        )

# https://json-schema.org/understanding-json-schema/reference/type
def _json_schema(type_hint: Type | UnionType) -> dict:
    origin = get_origin(type_hint)
    args = get_args(type_hint)
    if origin in (Union, UnionType):
        return {
            "anyOf": [_json_schema(arg) for arg in args]
        }

    # non-generic types
    if origin is None:
        origin = type_hint  

    # TypedDict classes expose __annotations__ and required/optional key metadata.
    if isinstance(origin, type) and hasattr(origin, "__annotations__") and hasattr(origin, "__total__"):
        field_hints = get_type_hints(origin)
        required_keys = set(getattr(origin, "__required_keys__", set(field_hints.keys())))

        return {
            "type": "object",
            "properties": {name: _json_schema(hint) for name, hint in field_hints.items()},
            "required": [name for name in field_hints if name in required_keys],
        }

    if origin is str:
        return {"type": "string"}
    elif origin is int:
        return {"type": "integer"}
    elif origin is float:
        return {"type": "number"}
    elif origin is bool:
        return {"type": "boolean"}
    elif origin is type(None):
        return {"type": "null"}
    elif origin is list:
        ret: dict = {"type": "array"}
        if args:
            ret["items"] = _json_schema(args[0])
        return ret
    elif origin is tuple:
        ret: dict = {"type": "array"}
        if args:
            ret["prefixItems"] = [_json_schema(arg) for arg in args]
        return ret
    elif origin is dict:
        # ignore arguments for dict, as JSON schema does not support arbitrary key types
        ret: dict = {"type": "object"}
        return ret
    
    else:
        raise ValueError(f"Unsupported type hint: {type_hint}")


def function_schema_to_openai_completion_tool_schema(schema: FunctionSchema) -> ChatCompletionToolParam:
    """Convert a FunctionSchema to OpenAI tool schema."""
    properties = {}
    required = []
    for param in schema.parameters:
        properties[param.name] = _json_schema(param.type_hint)
        if isinstance(param.default, FunctionParam._Empty):
            required.append(param.name)

    return ChatCompletionToolParam(
        type="function",
        function={
            "name": schema.name,
            "description": schema.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
    )

if __name__ == "__main__":
    # Example usage
    def example_function(param1: str |bool, param2: int = 42) -> bool:
        """This is an example function."""
        return True

    class ExampleDict(TypedDict):
        key1: str
        key2: int

    print(_json_schema(str | bool))
    print(_json_schema(Optional[str]))
    print(_json_schema(list[str]))
    print(_json_schema(ExampleDict))
