from dataclasses import dataclass
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import rich
import rich.panel

from ..config import confirm
from ..toolbox import ToolBox

CMD_ALLOWLIST = {
    "ls",
    "wc", 
    "echo",
    "pwd",
    "tree", 
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
    def command_path(self) -> Path:
        return Path(self.command)

    @property
    def is_bare_command(self) -> bool:
        return self.command_path.name == self.command

    @property
    def is_absolute_path(self) -> bool:
        return self.command_path.is_absolute()

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


def _note(message: str) -> None:
    panel = rich.panel.Panel(message, title="[bold yellow]Note[/bold yellow]", border_style="yellow")
    rich.print(panel)


def _resolve_command(spec: CommandSpec, allow_unlisted: bool) -> str | None:
    command = spec.command
    if not command:
        raise ValueError("Command must not be empty.")

    if not spec.is_bare_command:
        if not allow_unlisted or not spec.is_absolute_path:
            raise ValueError("Command must be a bare executable name unless explicitly confirmed as an absolute path.")
        if not spec.command_path.is_file():
            raise ValueError(f"Command '{command}' was not found.")
        return str(spec.command_path)

    executable = shutil.which(command)
    if executable is not None:
        return executable

    # Bare shell builtins such as `cd` are resolved by the invoked shell.
    return None


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
    if not spec.is_bare_command:
        if spec.is_absolute_path:
            reasons.append("uses an absolute path command")
        else:
            reasons.append("uses a non-bare command path")

    rejection_message = None
    if not spec.is_bare_command and not spec.is_absolute_path:
        rejection_message = "Only bare executable names or explicitly confirmed absolute command paths are allowed."
    elif not is_allowlisted:
        rejection_message = f"Command '{spec.command}' is not allowed."
    elif spec.uses_shell:
        rejection_message = "Shell operators are not allowed without confirmation."
    elif not spec.is_bare_command:
        rejection_message = "Absolute command paths are not allowed without confirmation."

    return ConfirmationPolicy(
        allow_unlisted=(not is_allowlisted) or (not spec.is_bare_command),
        reasons=tuple(reasons),
        rejection_message=rejection_message,
    )


def _confirm_command_execution(spec: CommandSpec, policy: ConfirmationPolicy) -> bool:
    if not policy.requires_confirmation:
        return False

    _note(f"Running command `{spec.command_line}` because it {' and '.join(policy.reasons)}")
    if not confirm("Allow command?", default=True):
        raise ValueError(policy.rejection_message or "Command execution was not confirmed.")

    return policy.allow_unlisted


def _run_shell_command(spec: CommandSpec) -> subprocess.CompletedProcess[str]:
    shell_executable = os.environ.get("SHELL")
    run_kwargs = {
        "shell": True,
        "capture_output": True,
        "text": True,
        "env": os.environ.copy(),
        "cwd": os.getcwd(),
    }
    if shell_executable:
        run_kwargs["executable"] = shell_executable
    return subprocess.run(spec.command_line, **run_kwargs)  # nosec B602


def cmd_exec( command: str,) -> str:
    """
    Runs a command and returns its output.
    Commands are always run through the current shell with inherited environment variables.
    Unlisted commands, shell operators, and absolute command paths still require confirmation.
    The command runs in the current process working directory, but cannot change it persistently.
    """
    spec = _parse_command_spec(command)
    policy = _confirmation_policy(spec)
    allow_unlisted = _confirm_command_execution(spec, policy)
    _resolve_command(spec, allow_unlisted=allow_unlisted)
    result = _run_shell_command(spec)

    if result.returncode != 0:
        raise RuntimeError(f"Command `{command}` failed with error: {result.stderr.strip()}")

    return result.stdout.strip()


def register_cmd_tools(toolbox: ToolBox):
    toolbox.register(cmd_exec)