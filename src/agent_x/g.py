
from fastmcp import FastMCP
from dataclasses import dataclass

@dataclass(frozen=True)
class GlobalContext:
    mcp: FastMCP = FastMCP()

__g = GlobalContext()
def global_context() -> GlobalContext:
    return __g