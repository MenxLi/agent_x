from __future__ import annotations
import sys

if sys.version_info >= (3, 13):
    from typing import TypeVar
else:
    # type var with `default` is available in Python 3.13 and later
    from typing_extensions import TypeVar

# https://pydantic.dev/docs/validation/latest/concepts/types/#named-recursive-types
if sys.version_info >= (3, 12):
    type JsonType = str | int | float | bool | None | dict[str, JsonType] | list[JsonType]
else:
    from typing import Union
    from typing_extensions import TypeAliasType
    JsonType = TypeAliasType(
        'JsonType',
        'Union[dict[str, JsonType], list[JsonType], str, int, float, bool, None]',  
    )

import json
from typing import Literal, Union, cast
from dataclasses import dataclass

class Result[T, E]:
    def __init__(self, value: Union[T, E], is_ok: bool):
        self._value = value
        self._is_ok = is_ok

    @classmethod
    def Ok(cls, value: T) -> Result[T, E]:
        return cls(value, True)

    @classmethod
    def Err(cls, error: E) -> Result[T, E]:
        return cls(error, False)

    def is_ok(self) -> bool:
        return self._is_ok

    def is_err(self) -> bool:
        return not self._is_ok

    def unwrap(self) -> T:
        if self.is_ok():
            return cast(T, self._value)
        else:
            raise Exception(f"Called unwrap on an Err value: {self._value}")

    def unwrap_err(self) -> E:
        if self.is_err():
            return cast(E, self._value)
        else:
            raise Exception(f"Called unwrap_err on an Ok value: {self._value}")
    
    @property
    def value(self) -> Union[T, E]:
        return self._value
    
    def value_json(self) -> JsonType:
        from .util import to_json_object
        return to_json_object(self._value)
    
    def value_str(self) -> str:
        if isinstance(self._value, str):
            return self._value
        return json.dumps(self.value_json(), ensure_ascii=False)

@dataclass
class ErrorInfo:
    error: str
    details: str

    def to_json(self) -> dict[str, str]:
        return {
            "error": self.error,
            "details": self.details,
        }

class CancelledError(Exception):
    """Raised when an operation is cancelled."""
    pass

type ModelCapabilityType = Literal['vision']
ModelCapabilityOptions = set(['vision'])

type ToolResultType = Result[JsonType, ErrorInfo]