from pathlib import Path
import shutil
from typing import Optional, Literal, Callable
from ..util import fmt_size, fmt_time

def __path_outof_root(path: str) -> bool:
    return not Path(path).resolve().is_relative_to(Path.cwd().resolve())

def fs_list(path: str, details = False) -> dict[Literal["directories", "files"], list[str]]:
    """
    List the contents of a directory at the specified path.
    Returns a list of file and directory names in the specified directory.
    """
    if __path_outof_root(path):
        raise ValueError("Path is out of the root directory.")
    if not details:
        return {
            "directories": [str(p.name) for p in Path(path).iterdir() if p.is_dir()],
            "files": [str(p.name) for p in Path(path).iterdir() if p.is_file()],
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
            "directories": [dir_with_details(p) for p in Path(path).iterdir() if p.is_dir()],
            "files": [file_with_details(p) for p in Path(path).iterdir() if p.is_file()],
        }

def fs_read_file(
    path: str,
    start_line: int = 0,
    end_line: Optional[int] = None,
) -> str:
    """
    Read content from a file at the specified path.
    You can specify the start and end line numbers to read a specific portion of the file. (start_line is inclusive, end_line is exclusive)
    """
    if __path_outof_root(path):
        raise ValueError("Path is out of the root directory.")
    lines = Path(path).read_text().splitlines()
    return "\n".join(lines[start_line:end_line])

def fs_write_file(path: str, content: str = "") -> Literal["OK"]:
    """
    Write content to a file at the specified path.
    If the file does not exist, it will be created.
    If the file already exists, its content will be overwritten.
    """
    if __path_outof_root(path):
        raise ValueError("Path is out of the root directory.")
    Path(path).write_text(content)
    return "OK"

def fs_write_binary_file(path: str, content: bytes) -> Literal["OK"]:
    """
    Write binary content to a file at the specified path.
    If the file does not exist, it will be created.
    If the file already exists, its content will be overwritten.
    """
    if __path_outof_root(path):
        raise ValueError("Path is out of the root directory.")
    Path(path).write_bytes(content)
    return "OK"

def fs_read_line(path: str, line_number: int) -> str:
    """
    Read content from a specific line in a file at the specified path.
    If the file does not exist, it will raise an error.
    """
    if __path_outof_root(path):
        raise ValueError("Path is out of the root directory.")
    lines = Path(path).read_text().splitlines()
    if line_number < 0 or line_number >= len(lines):
        raise ValueError("Line number is out of range.")
    return lines[line_number]

def fs_write_line(path: str, line_number: int, content: str = "") -> Literal["OK"]:
    """
    Write content to a specific line in a file at the specified path.
    If the file does not exist, it will raise an error.
    If the file already exists, the content at the specified line number will be overwritten, and other lines will remain unchanged.
    (Should use fs_read_line/fs_read_file to check the content of the line before writing to avoid accidentally overwriting important content.)
    """
    if __path_outof_root(path):
        raise ValueError("Path is out of the root directory.")
    if not Path(path).exists():
        raise FileNotFoundError("File does not exist.")
    lines = Path(path).read_text().splitlines()
    while len(lines) <= line_number:
        lines.append("")
    lines[line_number] = content
    Path(path).write_text("\n".join(lines))
    return "OK"

def fs_move(src: str, dst: str) -> Literal["OK"]:
    """
    Move (rename) a file or directory from src to dst.
    Basically same as `mv` command in Linux.
        - If dst is an existing directory, src will be moved into dst.
        - If dst is an existing file, it will be overwritten by src.
        - If dst does not exist, src will be renamed to dst.
    Under the hood it uses shutil.move, which can move both files and directories.
    """
    if __path_outof_root(src) or __path_outof_root(dst):
        raise ValueError("Path is out of the root directory.")
    if not Path(src).exists():
        raise FileNotFoundError("Source file/directory does not exist.")
    shutil.move(src, dst)
    return "OK"

def fs_mkdir(path: str) -> str:
    """
    Create a directory at the specified path.
    If the directory already exists, it does nothing.
    """
    if __path_outof_root(path):
        raise ValueError("Path is out of the root directory.")
    Path(path).mkdir(exist_ok=True)
    return "OK"

def expose_fs_tools(readonly: bool = False) -> list[Callable]:
    tools = [
        fs_list,
        fs_read_file,
        fs_read_line,
    ]
    if not readonly:
        tools.extend([
            fs_write_file,
            fs_write_line,
            fs_write_binary_file,
            fs_mkdir,
            fs_move,
        ])
    return tools