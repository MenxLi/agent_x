from dataclasses import dataclass
import shlex
import shutil
import subprocess
from pathlib import Path

import rich
import rich.panel
import rich.prompt

from ..toolbox import ToolBox

CMD_ALLOWLIST = {
    "ls",
    "wc", 
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


@dataclass(frozen=True)
class CommandSpec:
    command_line: str
    argv: list[str]
    operators: list[str]

    @property
    def command(self) -> str:
        return self.argv[0]

    @property
    def uses_shell(self) -> bool:
        return bool(self.operators)


@dataclass(frozen=True)
class ConfirmationPolicy:
    allow_unlisted: bool
    reasons: tuple[str, ...]
    rejection_message: str | None

    @property
    def requires_confirmation(self) -> bool:
        return bool(self.reasons)


def _confirm(message: str, *, default: bool) -> bool:
    return rich.prompt.Confirm.ask(message, default=default)


def _note(message: str) -> None:
    panel = rich.panel.Panel(message, title="[bold yellow]Note[/bold yellow]", border_style="yellow")
    rich.print(panel)


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


def _parse_command_spec(command_line: str) -> CommandSpec:
    if not command_line.strip():
        raise ValueError("Command must not be empty.")

    lexer = shlex.shlex(command_line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    argv = list(lexer)
    if not argv:
        raise ValueError("Command must not be empty.")

    operators = sorted({token for token in argv if token in SHELL_OPERATORS})
    return CommandSpec(command_line=command_line, argv=argv, operators=operators)


def _confirmation_policy(spec: CommandSpec) -> ConfirmationPolicy:
    is_allowlisted = spec.command in CMD_ALLOWLIST
    reasons: list[str] = []

    if not is_allowlisted:
        reasons.append("command is outside the allowlist")
    if spec.uses_shell:
        reasons.append(f"uses shell operators ({', '.join(spec.operators)})")

    rejection_message = None
    if not is_allowlisted:
        rejection_message = f"Command '{spec.command}' is not allowed."
    elif spec.uses_shell:
        rejection_message = "Shell operators are not allowed without confirmation."

    return ConfirmationPolicy(
        allow_unlisted=not is_allowlisted,
        reasons=tuple(reasons),
        rejection_message=rejection_message,
    )


def _confirm_command_execution(spec: CommandSpec, policy: ConfirmationPolicy) -> bool:
    if not policy.requires_confirmation:
        return False

    _note(f"Running command `{spec.command_line}` because it {' and '.join(policy.reasons)}")
    if not _confirm("Allow command?", default=True):
        raise ValueError(policy.rejection_message or "Command execution was not confirmed.")

    return policy.allow_unlisted


def _run_plain_command(spec: CommandSpec, executable: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([executable, *spec.argv[1:]], capture_output=True, text=True)  # nosec B603


def _run_shell_command(spec: CommandSpec) -> subprocess.CompletedProcess[str]:
    return subprocess.run(spec.command_line, shell=True, capture_output=True, text=True)  # nosec B602


def _run_command(spec: CommandSpec, executable: str) -> subprocess.CompletedProcess[str]:
    if spec.uses_shell:
        return _run_shell_command(spec)
    return _run_plain_command(spec, executable)


def cmd_exec(
    command_line: str,
) -> str:
    """
    Runs a command and returns its output.
    Plain commands are parsed without a shell and run with subprocess.run.
    Commands using shell operators require confirmation and are run with shell=True.
    """
    spec = _parse_command_spec(command_line)
    policy = _confirmation_policy(spec)
    allow_unlisted = _confirm_command_execution(spec, policy)
    executable = _resolve_command(spec.command, allow_unlisted=allow_unlisted)
    result = _run_command(spec, executable)

    if result.returncode != 0:
        raise RuntimeError(f"Command `{command_line}` failed with error: {result.stderr.strip()}")

    return result.stdout.strip()


def register_cmd_tools(toolbox: ToolBox):
    toolbox.register(cmd_exec)