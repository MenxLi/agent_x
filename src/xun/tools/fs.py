from pathlib import Path
import shutil
from dataclasses import dataclass
from typing import Optional, Literal, Callable
from ..context import global_context_guard
from ..toolcall import ToolCallContext as Context
from ..toolcall import tool_attr
from ..util import fmt_size, fmt_time

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

def __confirm_dangerous_operation(ctx: Context, operation: str) -> bool:
    message = f"Going to {operation}."
    return ctx.agent.display.get_confirm(
        "Proceed?", message,
        title="File System Operation Confirmation",
        subtitle=f"{ctx.agent.name} ({ctx.tool_name})",
        default=True,
    )

@tool_attr(name="temp_dir")
def fs_temp_dir(ctx: Context) -> str:
    """
    Get the path of the agent's temporary directory.
    This directory is unique for each of the agent. 
    Will be automatically cleaned up on agent's cleanup.
    """
    return str(ctx.agent.tempdir.path)

@tool_attr(name="list_dir")
def fs_list(ctx: Context, path: str, details = False) -> dict[Literal["directories", "files"], list[str]]:
    """
    List the contents of a directory at the specified path.
    Returns a list of file and directory names in the specified directory.
    """
    rpath = resolve_path(ctx, path).path
    if not details:
        return {
            "directories": [str(p.name) for p in rpath.iterdir() if p.is_dir()],
            "files": [str(p.name) for p in rpath.iterdir() if p.is_file()],
        }
    else:
        def file_with_details(p: Path) -> str:
            stat = p.stat()
            return f"{p.name} [{fmt_size(stat.st_size)}, modified: {fmt_time(stat.st_mtime)}, created: {fmt_time(stat.st_ctime)}, mode: {oct(stat.st_mode)}]"
        def dir_with_details(p: Path) -> str:
            stat = p.stat()
            n_content = len(list(p.iterdir()))
            return f"{p.name}/ [{n_content} items, created: {fmt_time(stat.st_ctime)}, mode: {oct(stat.st_mode)}]"

        return {
            "directories": [dir_with_details(p) for p in rpath.iterdir() if p.is_dir()],
            "files": [file_with_details(p) for p in rpath.iterdir() if p.is_file()],
        }

@tool_attr(name="file_info")
def fs_file_info(ctx: Context, path: str) -> dict:
    """
    Get metadata about a file without reading its content.
    Returns size, line count, last modified time, and whether it appears to be text or binary.
    """
    resolved = resolve_path(ctx, path).path
    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {resolved}")
    if not resolved.is_file():
        raise ValueError(f"Path is not a file: {resolved}")

    stat = resolved.stat()
    size = stat.st_size
    is_text = True
    line_count = 0

    try:
        with resolved.open("rb") as file:
            first_chunk = file.read(8192)
            is_text = b"\x00" not in first_chunk
            if not is_text:
                line_count = 0
            else:
                line_count = first_chunk.count(b"\n")
                has_data = bool(first_chunk)
                last_byte = first_chunk[-1:] if first_chunk else b""

                for chunk in iter(lambda: file.read(8192), b""):
                    has_data = True
                    line_count += chunk.count(b"\n")
                    last_byte = chunk[-1:]

                if has_data and last_byte != b"\n":
                    line_count += 1
    except OSError:
        pass

    return {
        "path": str(resolved),
        "size": f"{fmt_size(size)} ({size} bytes)",
        "line_count": line_count,
        "is_text": is_text,
        "last_modified": fmt_time(stat.st_mtime),
    }

@tool_attr(name="read_file")
def fs_read_file(
    ctx: Context,
    path: str,
    line_offset: int = 0,
    line_limit: Optional[int] = None, 
    include_line_numbers: bool = False
) -> str:
    """
    Read content from a file at the specified path.
    You can specify the starting line and ending line to read a specific range of lines from the file.
    - line_offset: The number of lines to skip from the start of the file (default is 0).
    - line_limit: The maximum number of lines to read (default is None, which means read all lines from the offset).
    - include_line_numbers: Whether to include line numbers in the output (default is False). \
        If set to True, each line will be prefixed with its line number (e.g., "1: line content"). \
        The line numbers will be based on the original file, not the offset.
    """
    rpath = resolve_path(ctx, path).path
    lines = rpath.read_text().splitlines()
    if line_offset >= len(lines):
        return ""
    end_line = line_offset + line_limit if line_limit is not None else None
    if include_line_numbers:
        return "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines[line_offset:end_line], start=line_offset))
    else:
        return "\n".join(lines[line_offset:end_line])

@tool_attr(name="write_file")
def fs_write_file(ctx: Context, path: str, content: str = "") -> Literal["OK"]:
    """
    Write content to a file at the specified path.
    If the file does not exist, it will be created.
    If the file already exists, its content will be overwritten.
    """
    resolved = resolve_path(ctx, path)
    if resolved.path.exists() and not resolved.in_tempdir:
        if not __confirm_dangerous_operation(ctx, f"Overwrite existing file `{resolved.path}`"):
            raise RuntimeError(f"Operation cancelled by user, file `{resolved.path}` was not overwritten.")
    resolved.path.write_text(content)
    return "OK"

@tool_attr(name="move")
def fs_move(ctx: Context, src: str, dst: str) -> Literal["OK"]:
    """
    Move (rename) a file or directory from src to dst.
    Basically same as `mv` command in Linux.
        - If dst is an existing directory, src will be moved into dst.
        - If dst is an existing file, it will be overwritten by src.
        - If dst does not exist, src will be renamed to dst.
    Under the hood it uses shutil.move, which can move both files and directories.
    """
    src_resolved = resolve_path(ctx, src)
    dst_resolved = resolve_path(ctx, dst)
    if not src_resolved.path.exists():
        raise FileNotFoundError("Source file/directory does not exist.")
    # If the source file is in temp dir, we can be more lenient. 
    # Otherwise, we require confirmation for move operation.
    if not src_resolved.in_tempdir and not __confirm_dangerous_operation(ctx, f"Move `{src_resolved.path}` to `{dst_resolved.path}`"):
        raise RuntimeError(f"Operation cancelled by user, `{src_resolved.path}` was not moved to `{dst_resolved.path}`.")
    shutil.move(src_resolved.path, dst_resolved.path)
    return "OK"

@tool_attr(name="copy")
def fs_copy(ctx: Context, src: str, dst: str) -> Literal["OK"]:
    """
    Copy a file or directory from src to dst.
    Basically same as `cp` command in Linux.
        - If src is a file:
            - If dst is an existing directory, src will be copied into dst.
            - If dst is an existing file, it will be overwritten by src.
            - If dst does not exist, src will be copied to dst.
        - If src is a directory:
            - If dst is an existing directory, src will be copied into dst (i.e. dst/src).
            - If dst does not exist, src will be copied to dst (i.e. dst will be created as a copy of src).
            - If dst is an existing file, an error will be raised.
    Under the hood it uses shutil.copy2 for files and shutil.copytree for directories.
    """
    src_resolved = resolve_path(ctx, src)
    dst_resolved = resolve_path(ctx, dst)
    if not src_resolved.path.exists():
        raise FileNotFoundError("Source file/directory does not exist.")
    if src_resolved.path.is_file():
        if dst_resolved.path.exists() and dst_resolved.path.is_dir():
            shutil.copy2(src_resolved.path, dst_resolved.path / src_resolved.path.name)
        else:
            shutil.copy2(src_resolved.path, dst_resolved.path)
    elif src_resolved.path.is_dir():
        if dst_resolved.path.exists() and dst_resolved.path.is_file():
            raise FileExistsError("Destination path exists as a file, cannot copy a directory onto a file.")
        elif dst_resolved.path.exists() and dst_resolved.path.is_dir():
            shutil.copytree(src_resolved.path, dst_resolved.path / src_resolved.path.name)
        else:
            shutil.copytree(src_resolved.path, dst_resolved.path)
    return "OK"

@tool_attr(name="mkdir")
def fs_mkdir(ctx: Context, path: str) -> Literal["OK"]:
    """
    Create a directory at the specified path.
    If the directory already exists, it does nothing.
    """
    rpath = resolve_path(ctx, path).path
    rpath.mkdir(exist_ok=True)
    return "OK"

@tool_attr(name="delete")
def fs_delete(ctx: Context, path: str) -> Literal["OK"]:
    """
    Delete a file or directory at the specified path.
    If the path is a directory, it will be deleted recursively.
    """
    resolved = resolve_path(ctx, path)
    p = resolved.path
    if not p.exists():
        raise FileNotFoundError("File/directory does not exist.")

    if not resolved.in_tempdir and not __confirm_dangerous_operation(ctx, f"Delete `{resolved.path}`"):
        raise RuntimeError(f"Operation cancelled by user, `{resolved.path}` was not deleted.")

    if p.is_file():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)
    return "OK"

@tool_attr(name="request_image")
def fs_request_image(ctx: Context, src: str) -> Literal["OK"]:
    """
    You can request an image using the `request_image` tool.
    The input can be a single local image path or URL.

    The image will be added to the conversation as a user message with an empty text content.

    Call this tool whenever:
    - The request depends on visual details
    - The input is ambiguous without seeing an image
    - The task involves inspecting objects, scenes, diagrams, or UI
    """
    def is_url(path: str) -> bool:
        return path.startswith("http://") or path.startswith("https://")
    if not is_url(src):
        src_resolved = resolve_path(ctx, src)
        if not src_resolved.path.exists():
            raise FileNotFoundError("Source image file does not exist.")
        src = str(src_resolved.path)
    ctx.agent.conversation.add_user_message("", images=[src])
    return "OK"

def expose_fs_tools() -> list[Callable]:
    tools = [
        fs_list,
        fs_read_file,
        fs_file_info,
        fs_temp_dir,
        fs_write_file,
        fs_mkdir,
        fs_move,
        fs_copy, 
        fs_delete,
        fs_request_image,
    ]
    return tools