from pathlib import Path
from typing import Optional, Literal

from ..toolbox import ToolBox


def __path_outof_root(path: str) -> bool:
    return not Path(path).resolve().is_relative_to(Path.cwd().resolve())


def fs_list(path: str) -> dict[Literal["directories", "files"], list[str]]:
    """
    List the contents of a directory at the specified path.
    Returns a list of file and directory names in the specified directory.
    """
    if __path_outof_root(path):
        raise ValueError("Path is out of the root directory.")
    return {
        "directories": [str(p.name) for p in Path(path).iterdir() if p.is_dir()],
        "files": [str(p.name) for p in Path(path).iterdir() if p.is_file()],
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


def fs_write_file(path: str, content: str = "") -> str:
    """
    Write content to a file at the specified path.
    If the file does not exist, it will be created.
    If the file already exists, its content will be overwritten.
    """
    if __path_outof_root(path):
        raise ValueError("Path is out of the root directory.")
    Path(path).write_text(content)
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


def register_fs_tools(
    toolbox: ToolBox,
    allow_write: bool = True,
):
    toolbox.register(fs_list)
    toolbox.register(fs_read_file)
    if allow_write:
        toolbox.register(fs_mkdir)
        toolbox.register(fs_write_file)