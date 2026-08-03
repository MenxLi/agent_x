import py_compile
from typing import Callable, Literal
from ..toolcall import ToolCallContext
from .fs import resolve_path

def check_syntax_python(
    ctx: ToolCallContext,
    path: str,
)-> dict[Literal["valid", "error_msg"], bool | str]:
    """
    Check the syntax of a Python file by compiling it.
    Returns whether the file is syntactically valid, and any error message if not.
    Does not execute the file — only parses it.
    """
    resolved = resolve_path(ctx, path).path

    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {resolved}")

    if not resolved.is_file():
        raise ValueError(f"Path is not a file: {resolved}")

    try:
        py_compile.compile(str(resolved), doraise=True)
        return {"valid": True, "error_msg": ""}
    except py_compile.PyCompileError as e:
        return {"valid": False, "error_msg": str(e)}


def expose_diagnostic_tools() -> list[Callable]:
    return [check_syntax_python]