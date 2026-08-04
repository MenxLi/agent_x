from __future__ import annotations
from typing import Callable, Union, overload
from typing import cast
from functools import wraps
from dataclasses import dataclass
import json
from .util import to_json_object
from .types import JsonType

def is_except_safe_wrapper(fn: Callable[..., object]) -> bool:
    return getattr(fn, "__xun_except_safe_wrapper__", False)

def mark_except_safe_wrapper(fn: Callable[..., object]) -> None:
    setattr(fn, "__xun_except_safe_wrapper__", True)

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
        return to_json_object(self._value)
    
    def value_str(self) -> str:
        if isinstance(self._value, str):
            return self._value
        return json.dumps(self.value_json(), ensure_ascii=False)

@overload
def except_safe[**P, T, E](fn: Callable[P, Result[T, E]]) -> Callable[P, Result[T, E | ErrorInfo]]: ...  # type: ignore[misc]
@overload
def except_safe[**P, R](fn: Callable[P, R]) -> Callable[P, Result[R, ErrorInfo]]: ...

def except_safe[**P](fn: Callable):
    if is_except_safe_wrapper(fn):
        return fn

    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Result:
        try:
            result = fn(*args, **kwargs)
            if isinstance(result, Result):
                return result
            return Result.Ok(result)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            return Result.Err(ErrorInfo(
                error=str(exc),
                details=repr(exc),
            ))

    mark_except_safe_wrapper(wrapper)
    return wrapper

@dataclass
class ErrorInfo:
    error: str
    details: str

    def to_json(self) -> dict[str, str]:
        return {
            "error": self.error,
            "details": self.details,
        }