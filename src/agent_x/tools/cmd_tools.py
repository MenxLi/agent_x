import shlex
import shutil
import subprocess
from pathlib import Path

import rich
import rich.prompt

from ..toolbox import ToolBox

CMD_ALLOWLIST = {
    "ls",
    "echo",
    "pwd",
    "date",
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
    "dmesg",
    "journalctl",
    "lsb_release",
    "uname",
    "os-release",
}

SHELL_OPERATORS = {";", "&&", "&", "||", "|", ">", ">>", "<", "<<", "(", ")"}


def _confirm(message: str, *, default: bool) -> bool:
    return rich.prompt.Confirm.ask(message, default=default)


def _note(message: str) -> None:
    rich.print(f"[bold yellow]Note:[/bold yellow] {message}")


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

    executable = shutil.which(command)
    if executable is None:
        raise ValueError(f"Command '{command}' was not found.")

    return executable


def _parse_command_line(command_line: str) -> list[str]:
    if not command_line.strip():
        raise ValueError("Command must not be empty.")

    lexer = shlex.shlex(command_line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    argv = list(lexer)
    if not argv:
        raise ValueError("Command must not be empty.")

    return argv


def _shell_operators(argv: list[str]) -> list[str]:
    return sorted({token for token in argv if token in SHELL_OPERATORS})


def _allow_command(command: str, command_line: str) -> bool:
    if command in CMD_ALLOWLIST:
        return False

    _note(f"Running command `{command_line}`")
    if not _confirm("Allow command outside allowlist?", default=True):
        raise ValueError(f"Command '{command}' is not allowed.")
    return True


def _run_plain_command(argv: list[str], executable: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([executable, *argv[1:]], capture_output=True, text=True)  # nosec B603


def _run_shell_command(command_line: str, operators: list[str]) -> subprocess.CompletedProcess[str]:
    operator_list = ", ".join(operators)
    _note(f"Running shell command with operators ({operator_list}): `{command_line}`")
    if not _confirm("Allow shell operators?", default=False):
        raise ValueError(f"Shell operators are not allowed without confirmation: {operator_list}")
    return subprocess.run(command_line, shell=True, capture_output=True, text=True)  # nosec B602


def cmd_exec(
    command_line: str,
) -> str:
    """
    Runs a command and returns its output.
    Plain commands are parsed without a shell and run with subprocess.run.
    Commands using shell operators require confirmation and are run with shell=True.
    For example:
        cmd_exec("uname -a")
    """
    argv = _parse_command_line(command_line)
    command = argv[0]
    operators = _shell_operators(argv)
    allow_unlisted = _allow_command(command, command_line)
    executable = _resolve_command(command, allow_unlisted=allow_unlisted)

    if operators:
        result = _run_shell_command(command_line, operators)
    else:
        result = _run_plain_command(argv, executable)

    if result.returncode != 0:
        raise RuntimeError(f"Command `{command_line}` failed with error: {result.stderr.strip()}")

    return result.stdout.strip()


def register_cmd_tools(toolbox: ToolBox):
    toolbox.register(cmd_exec)