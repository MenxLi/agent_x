import fnmatch
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from ..context import global_context_guard
from ..toolcall import ToolCallContext as Context


@dataclass
class ResolvedPath:
    path: Path
    in_workdir: bool
    in_tempdir: bool


def resolve_path(ctx: Context, path: str | Path, raise_on_invalid: bool = True) -> ResolvedPath:
    """ Resolve a path relative to the agent's current working directory. """
    p = Path(path)
    base = ctx.agent.workdir if not p.is_absolute() else Path()
    resolved = base / p if not p.is_absolute() else p

    # check
    cwd_abs = ctx.agent.workdir.resolve()
    resolved_abs = resolved.resolve()
    def is_in_tempdir():
        with global_context_guard as global_context:
            temp_dirs = [tmpdir.exist_path for tmpdir in global_context.tempdirs if tmpdir.exist_path is not None]
        return any(
            resolved_abs == temp_dir.resolve() or temp_dir.resolve() in resolved_abs.parents
            for temp_dir in temp_dirs
        )
    in_tempdir = is_in_tempdir()
    in_workdir = resolved_abs.is_relative_to(cwd_abs)
    if raise_on_invalid and not in_workdir and not in_tempdir:
        raise ValueError(f"Path {resolved_abs} is not within the current working directory or any agent's temporary directory.")
    return ResolvedPath(resolved, in_workdir, in_tempdir)


def confirm_dangerous_operation(
    ctx: Context, 
    operation: str, 
    title = "Confirm Dangerous Operation",
    ) -> bool:
    message = f"Going to {operation}."
    return ctx.agent.display.get_confirm(
        "Proceed?", message,
        title=title,
        subtitle=f"{ctx.agent.name} ({ctx.tool_name})",
        default=True,
    )


def is_path_binary(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read(8192)
            return b"\x00" in chunk
    except OSError:
        return True


def glob_match(pattern: str, name: str) -> bool:
    return fnmatch.fnmatch(name, pattern)


class WriteAllowList:
    """
    Track paths that the agent is allowed to write to.
    Should be stored in the agent's state, not global.
    """
    def __init__(self, allowlist: Optional[list[Path]] = None):
        self.allowlist = allowlist or []
    
    def add(self, path: Path):
        """
        Add a path to the allowlist if it's a file.
        Used after a write operation succeeds to grant future permission.
        """
        if path.is_file():
            self.allowlist.append(path)
    
    def has(self, path: Path) -> bool:
        """Check if a path is in the allowlist."""
        return any(path.resolve() == allowed.resolve() for allowed in self.allowlist)


def write_allowlist(ctx: Context) -> WriteAllowList:
    """Get or create a WriteAllowList stored in the agent's state."""
    if "_fs_write_allowlist" not in ctx.agent.state:
        ctx.agent.state["_fs_write_allowlist"] = WriteAllowList()
    return ctx.agent.state["_fs_write_allowlist"]