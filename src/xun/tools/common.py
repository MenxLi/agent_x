import fnmatch
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Sequence
from PIL.Image import Image

from ..hooks import HookArgs
from ..toolcall import ToolCallContext as Context
from ..util import image_to_url


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
    if (temp_dir := ctx.agent.tempdir.exist_path) is not None:
        temp_dir_abs = temp_dir.resolve()
        in_tempdir = resolved_abs == temp_dir_abs or temp_dir_abs in resolved_abs.parents
    else:
        in_tempdir = False
    in_workdir = resolved_abs.is_relative_to(cwd_abs)
    if raise_on_invalid and not in_workdir and not in_tempdir:
        raise ValueError(f"Path {resolved_abs} is not within the current working directory or the agent's temporary directory.")
    return ResolvedPath(resolved, in_workdir, in_tempdir)


def defer_tool_image(ctx: Context, image: str | Image) -> None:
    """Add an image after the current batch of tool results is committed."""
    image_url = image_to_url(image)

    def add_image(args: HookArgs.AfterExecutionStepArgs) -> None:
        args.agent.conversation.add_user_message("", images=[image_url])

    ctx.agent.hooks.after_execution_step.add_once(add_image)


def is_path_binary(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read(8192)
            return b"\x00" in chunk
    except OSError:
        return True


def glob_match(pattern: str, name: str) -> bool:
    return fnmatch.fnmatch(name, pattern)


def git_ignored_paths(base: Path, paths: list[str]) -> set[str]:
    """
    Return the subset of `paths` that are ignored by git at `base` (a git repo root).
    Paths are given relative to `base`. Uses `git check-ignore --stdin` in one call.
    Returns an empty set if the query fails (e.g. not a git repo), i.e. no filtering.
    """
    if not paths:
        return set()
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            cwd=base,
            input="\n".join(str(p) for p in paths) + "\n",
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if result.returncode not in (0, 1):
        return set()
    return {line for line in result.stdout.splitlines() if line}


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


class CommandExecutionAllowList:
    """
    Track commands that the agent is allowed to execute.
    Should be stored in the agent's state, not global.
    """
    def __init__(self):
        self._allowlist = {
            "ls",
            "wc",
            "echo",
            "pwd",
            "tree",
            "date",
            "which",
            "whoami",
            "uptime",
            "df",
            "free",
            "ps",
            "top",
            "netstat",
            "ifconfig",
            "ping",
            "traceroute",
            "curl",
            "wget",
            "dig",
            "nslookup",
            "ip",
            "ss",
            "lsof",
            "lspci",
            "lscpu",
            "lsusb",
            "lsblk",
            "dmesg",
            "journalctl",
            "lsb_release",
            "uname",

            "grep",
            "head",
            "tail",
            "sed", 
            "cat",
            "nl", 

            "nvidia-smi",

            "python -m unittest",
            "python3 -m unittest",
            "python -m pytest",
            "python3 -m pytest",

            "git status",
            "git --no-pager status",
            "git log",
            "git --no-pager log",
            "git diff",
            "git --no-pager diff",
            "git show",
            "git --no-pager show",
        }
    
    @property
    def allowlist(self) -> set[str]:
        return self._allowlist
    
    # Multi-token allowlist entries act as command prefixes, so a command is
    # auto-approved when it starts with one of them (e.g. "git diff --cached"
    # starts with the allowlisted "git diff"). Matching on whole tokens keeps the
    # boundary on argument edges, so "git status" does not match "git statusx".
    @property
    def allowlist_prefix(self) -> Sequence[tuple[str, ...]]:
        return [tuple(entry.split()) for entry in self._allowlist if " " in entry]
    
    def add(self, command: str):
        """Add a command to the allowlist."""
        self._allowlist.add(command)
    
    def has(self, command: str) -> bool:
        """Check if a command is in the allowlist."""
        return command in self._allowlist

@dataclass
class Policy:
    write_allowlist: WriteAllowList
    command_allowlist: CommandExecutionAllowList

def get_policy(ctx: Context) -> Policy:
    """Get or create a Policy stored in the agent's state."""
    POLICY_TAG = "__builtin_tool_policy"
    if POLICY_TAG not in ctx.agent.state:
        ctx.agent.state[POLICY_TAG] = Policy(
            write_allowlist=WriteAllowList(), 
            command_allowlist=CommandExecutionAllowList()
            )
    return ctx.agent.state[POLICY_TAG]
