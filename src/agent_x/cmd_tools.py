import subprocess
import shutil
from pathlib import Path
import rich
import rich.prompt
from .g import global_context

cmd_allowlist = [
    "ls", "cat", "echo", "pwd", "date", "whoami", "uptime", "df", "free", "ps", "top", "netstat", "ifconfig", "ping", "traceroute", 
    "curl", "wget", "dig", "nslookup", "ip", "ss", "lsof", "dmesg", "journalctl", 
    "nvidia-smi", "lsb_release", "uname", 
]

SAFE_EXEC_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

def _resolve_command(command: str, allow_unlisted: bool) -> str:
    if not command:
        raise ValueError("Command must not be empty.")

    command_path = Path(command)
    if allow_unlisted and command_path.is_absolute():
        if not command_path.is_file():
            raise ValueError(f"Command '{command}' was not found.")
        return str(command_path)

    if command_path.name != command:
        raise ValueError("Command must be a bare executable name unless explicitly confirmed as an absolute path.")

    lookup_path = None if allow_unlisted else SAFE_EXEC_PATH
    executable = shutil.which(command, path=lookup_path)
    if executable is None:
        if allow_unlisted:
            raise ValueError(f"Command '{command}' was not found.")
        raise ValueError(f"Command '{command}' was not found in the trusted executable path.")

    return executable

def cmd_exec(
    command: str,
    args: list[str] | None = None,
) -> str:
    """
    Runs a command and returns its output.
    Command will be run with subprocess.run via:
        subprocess.run([resolved_command] + args, capture_output=True, text=True)
    """
    argv = list(args or [])
    allow_unlisted = False

    if command not in cmd_allowlist:
        rich.print(f"[bold red]Note:[/bold red] Running command `{' '.join([command] + argv)}`")
        if not rich.prompt.Confirm.ask("Allow?", default=True):
            raise ValueError(f"Command '{command}' is not allowed.")
        allow_unlisted = True

    executable = _resolve_command(command, allow_unlisted=allow_unlisted)
    result = subprocess.run([executable] + argv, capture_output=True, text=True)  # nosec B603
    if result.returncode != 0:
        raise RuntimeError(f"Command `{' '.join([command] + argv)}` failed with error: {result.stderr.strip()}")

    return result.stdout.strip()

def register_cmd_tools():
    mcp = global_context().mcp
    mcp.tool()(cmd_exec)