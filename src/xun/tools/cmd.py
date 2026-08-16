from dataclasses import dataclass
import os
import shlex
import shutil
import signal
import subprocess
from pathlib import Path
from pydantic import BaseModel
from typing import Callable, Optional, Literal
from typing_extensions import TypedDict
from ..toolcall import ToolCallContext
from .common import resolve_path

CMD_ALLOWLIST = {
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

# Multi-token allowlist entries act as command prefixes, so a command is
# auto-approved when it starts with one of them (e.g. "git diff --cached"
# starts with the allowlisted "git diff"). Matching on whole tokens keeps the
# boundary on argument edges, so "git status" does not match "git statusx".
CMD_ALLOWLIST_PREFIXES = tuple(
    tuple(entry.split()) for entry in CMD_ALLOWLIST if " " in entry
)

SHELL_OPERATORS = {";", "&&", "&", "||", "|", ">", ">>", "<", "<<", ">&", "<&", "(", ")"}
AUTO_APPROVED_SHELL_OPERATORS = {";", "&&", "||", "|", "(", ")"}
COMMAND_CHAIN_OPERATORS = {";", "&&", "||", "|"}
SAFE_REDIRECTION_TARGETS = {"/dev/null"}

class RiskAccessResult(BaseModel):
    policy: Literal['allow', 'unsure', 'reject']
    reason: Optional[str] = None
def agent_risk_access(
    ctx: ToolCallContext,
    cmd: str, 
    workdir: Path,
    extra_allowed_paths: list[Path] = [],
    ) -> RiskAccessResult:
    from .. import Agent, NullDisplay, ToolBox
    from .fs import fs_read_file, fs_list
    agent = Agent(
        name="Command Risk Assessment", 
        display=NullDisplay(), 
        toolbox = ToolBox().register(fs_read_file, fs_list),
        api_call_semaphore=ctx.agent.api_call_semaphore, 
    ).system(
        "You are an agent that is responsible for accessing shell commands. "
        "The command will be run under given working directory. "
        "You must determine whether the command is safe to execute (allow), requires user confirmation (unsure), or should be rejected outright (reject).\n\n"

        "The command should be rejected if it is potentially harmful, or work outside the working directory or allowed paths (subdirectories are allowed). \n"
        "A command is doomed to be potentially harmful if it may disrupt the system or irreversibly modify important files. \n"
        "The command is considered safe if it is a readonly command, \n"
        "Otherwise, it should be confirmed with the user before execution. \n\n"

        "You have a tool to read files (only within the allowed paths), you should avoid read the file unless necessary to determine the risk of the command. \n"
        "If you determine that the command is safe, you can output a reason as null, otherwise, you should provide a concise (less than 20 words) reason for your decision. \n"
    ).instruct(
        f"Given the command: `{cmd}`\n"
        f"Current working directory: `{workdir} (absolute path: {workdir.resolve()})`\n"
        f"Extra allowed paths: `{extra_allowed_paths}`\n"
        f"Please determine the risk access policy for this command. "
    )
    res = agent.execute(schema=RiskAccessResult)
    if res.is_err():
        return RiskAccessResult(policy='unsure', reason=f"Failed to assess command risk: {res.unwrap_err()}")
    return res.unwrap()

@dataclass(frozen=True)
class CommandSegment:
    """
    Represents a shell command segment (executable + arguments) that is delimited by command operators.
    This allows checking allowlists based on full command invocations, e.g., "python -m unittest".
    """
    tokens: tuple[str, ...]

    @property
    def executable(self) -> str:
        """The first token, which is the command name or path."""
        return self.tokens[0] if self.tokens else ""

    @property
    def command_str(self) -> str:
        """Reconstruct the command as it would appear."""
        # Use a simple space join. This is for comparison against allowlist entries.
        # Note: quoting and whitespace may differ, but we expect allowlist entries to be in a normalized form.
        return " ".join(self.tokens)

    def _matches_allowlist_prefix(self, prefix: tuple[str, ...]) -> bool:
        """Check if the segment starts with the given prefix at token boundaries."""
        return len(self.tokens) >= len(prefix) and self.tokens[:len(prefix)] == prefix

    @property
    def is_allowlisted(self) -> bool:
        """
        Check if this command segment is allowed.
        It is allowed if:
          - The executable (first token) is in CMD_ALLOWLIST.
          - OR, the command starts with a multi-token entry in CMD_ALLOWLIST
            (e.g. "git diff --cached" starts with the allowlisted "git diff").
        """
        if self.executable in CMD_ALLOWLIST:
            return True
        if self.command_str in CMD_ALLOWLIST:
            return True
        return any(
            self._matches_allowlist_prefix(prefix) for prefix in CMD_ALLOWLIST_PREFIXES
        )


@dataclass(frozen=True)
class ExecutableSpec:
    value: str

    @property
    def path(self) -> Path:
        return Path(self.value)

    @property
    def is_bare_command(self) -> bool:
        return self.path.name == self.value

    @property
    def is_absolute_path(self) -> bool:
        return self.path.is_absolute()

    @property
    def is_allowlisted(self) -> bool:
        return self.is_bare_command and self.value in CMD_ALLOWLIST


@dataclass(frozen=True)
class CommandSpec:
    command_line: str
    argv: tuple[str, ...]
    commands: tuple[ExecutableSpec, ...]
    segments: tuple[CommandSegment, ...]

    @property
    def disallowed_operators(self) -> tuple[str, ...]:
        return _disallowed_shell_operators(self.argv)


def _safe_redirection_span(argv: tuple[str, ...], index: int) -> int | None:
    if index + 1 < len(argv) and argv[index] == ">" and argv[index + 1] in SAFE_REDIRECTION_TARGETS:
        return 2

    if (
        index + 2 < len(argv)
        and argv[index] in {"1", "2"}
        and argv[index + 1] == ">"
        and argv[index + 2] in SAFE_REDIRECTION_TARGETS
    ):
        return 3

    if index + 2 < len(argv) and argv[index] == "2" and argv[index + 1] == ">&" and argv[index + 2] == "1":
        return 3

    return None


def _disallowed_shell_operators(argv: tuple[str, ...]) -> tuple[str, ...]:
    disallowed: set[str] = set()
    index = 0

    while index < len(argv):
        token = argv[index]

        if token in AUTO_APPROVED_SHELL_OPERATORS:
            index += 1
            continue

        safe_redirection_span = _safe_redirection_span(argv, index)
        if safe_redirection_span is not None:
            index += safe_redirection_span
            continue

        if token in SHELL_OPERATORS:
            disallowed.add(token)

        index += 1

    return tuple(sorted(disallowed))


@dataclass(frozen=True)
class ConfirmationPolicy:
    allow_unlisted: bool
    reasons: tuple[str, ...]
    rejection_message: str | None

    @property
    def requires_confirmation(self) -> bool:
        return bool(self.reasons)


def _extract_exes(argv: list[str]) -> tuple[ExecutableSpec, ...]:
    """Original extraction: extract each executable token from the command line."""
    commands: list[ExecutableSpec] = []
    expect_command = True

    for token in argv:
        if token == "(":
            expect_command = True
            continue
        if token == ")":
            continue
        if token in COMMAND_CHAIN_OPERATORS:
            expect_command = True
            continue
        if expect_command and token not in SHELL_OPERATORS:
            commands.append(ExecutableSpec(token))
            expect_command = False

    return tuple(commands)


def _extract_segments(argv: list[str]) -> tuple[CommandSegment, ...]:
    """Extract full command segments, splitting on chain operators."""
    segments = []
    current: list[str] = []

    def flush():
        if current:
            segments.append(CommandSegment(tuple(current)))
            current.clear()

    for token in argv:
        if token in COMMAND_CHAIN_OPERATORS:
            flush()
            continue
        if token in ("(", ")"):
            continue
        # Include all other tokens in the segment (operators like >, <, etc.)
        current.append(token)

    flush()
    return tuple(segments)


def _parse_command_spec(command_line: str) -> CommandSpec:
    if not command_line.strip():
        raise ValueError("Command must not be empty.")

    lexer = shlex.shlex(command_line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    argv = list(lexer)
    if not argv:
        raise ValueError("Command must not be empty.")

    commands = _extract_exes(argv)
    if not commands:
        raise ValueError("Command must contain an executable.")

    segments = _extract_segments(argv)

    return CommandSpec(
        command_line=command_line,
        argv=tuple(argv),
        commands=commands,
        segments=segments,
    )


def _first_matching_command(
    spec: CommandSpec,
    predicate: Callable[[ExecutableSpec], bool],
) -> ExecutableSpec | None:
    return next((command for command in spec.commands if predicate(command)), None)


def _first_matching_segment(
    segments: tuple[CommandSegment, ...],
    predicate: Callable[[CommandSegment], bool],
) -> CommandSegment | None:
    return next((seg for seg in segments if predicate(seg)), None)


def _command_path_reason(spec: CommandSpec) -> str | None:
    if _first_matching_command(spec, lambda command: not command.is_bare_command and not command.is_absolute_path):
        return "command chain includes a non-bare command path"
    if _first_matching_command(spec, lambda command: command.is_absolute_path):
        return "command chain includes an absolute path command"
    return None


def _shell_syntax_reasons(command_line: str) -> tuple[str, ...]:
    reasons: list[str] = []
    if "`" in command_line:
        reasons.append("uses backtick command substitution")
    if "\n" in command_line or "\r" in command_line:
        reasons.append("uses line-separated commands")
    return tuple(reasons)


def _command_substitutions(command_line: str) -> tuple[str, ...]:
    substitutions: list[str] = []
    index = 0
    quote: str | None = None

    while index < len(command_line):
        character = command_line[index]
        if character == "\\" and quote != "'":
            index += 2
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            index += 1
            continue
        if quote != "'" and command_line.startswith("$(", index):
            start = index + 2
            depth = 1
            cursor = start
            inner_quote: str | None = None
            while cursor < len(command_line) and depth:
                inner_character = command_line[cursor]
                if inner_character == "\\" and inner_quote != "'":
                    cursor += 2
                    continue
                if inner_character in {"'", '"'}:
                    if inner_quote is None:
                        inner_quote = inner_character
                    elif inner_quote == inner_character:
                        inner_quote = None
                elif inner_quote != "'" and command_line.startswith("$(", cursor):
                    depth += 1
                    cursor += 1
                elif inner_quote is None and inner_character == ")":
                    depth -= 1
                    if depth == 0:
                        substitutions.append(command_line[start:cursor])
                        index = cursor
                cursor += 1
        index += 1

    return tuple(substitutions)


def _command_substitution_reasons(command_line: str) -> tuple[str, ...]:
    reasons: list[str] = []
    for substitution in _command_substitutions(command_line):
        try:
            policy = _confirmation_policy(_parse_command_spec(substitution))
        except ValueError:
            reasons.append("contains an invalid command substitution")
            continue
        if policy.requires_confirmation:
            reasons.append(f"command substitution requires confirmation: $({substitution})")
    return tuple(reasons)


def _confirmation_policy(spec: CommandSpec) -> ConfirmationPolicy:
    reasons: list[str] = []

    # Check if any segment is not allowlisted.
    unallowlisted_segment = _first_matching_segment(spec.segments, lambda seg: not seg.is_allowlisted)
    path_reason = _command_path_reason(spec)
    syntax_reasons = _shell_syntax_reasons(spec.command_line)
    substitution_reasons = _command_substitution_reasons(spec.command_line)

    if unallowlisted_segment is not None:
        reasons.append(f"command '{unallowlisted_segment.executable}' is not allowlisted in full command '{unallowlisted_segment.command_str}'")
    if spec.disallowed_operators:
        reasons.append(f"uses shell operators requiring confirmation ({', '.join(spec.disallowed_operators)})")
    if path_reason is not None:
        reasons.append(path_reason)
    reasons.extend(syntax_reasons)
    reasons.extend(substitution_reasons)

    rejection_message = None
    if path_reason == "command chain includes a non-bare command path":
        rejection_message = "Only bare executable names or explicitly confirmed absolute command paths are allowed."
    elif unallowlisted_segment is not None:
        rejection_message = f"Command '{unallowlisted_segment.executable}' is not allowlisted."
    elif spec.disallowed_operators:
        rejection_message = "Shell redirections and background operators are not allowed without confirmation, except for exact safe forms like 2>&1 and >/dev/null."
    elif path_reason is not None:
        rejection_message = "Absolute command paths are not allowed without confirmation."
    elif syntax_reasons:
        rejection_message = "Backtick command substitution and line-separated commands are not allowed without confirmation."
    elif substitution_reasons:
        rejection_message = "A command substitution contains a command that is not allowlisted."

    return ConfirmationPolicy(
        allow_unlisted=(unallowlisted_segment is not None) or (path_reason is not None),
        reasons=tuple(reasons),
        rejection_message=rejection_message,
    )


def _confirm_command_execution(
    ctx: ToolCallContext, 
    spec: CommandSpec, 
    policy: ConfirmationPolicy, 
    cd: Optional[str] = None
    ) -> bool:
    if not policy.requires_confirmation:
        return False
    
    resolved_cd = resolve_path(ctx, cd, raise_on_invalid=False) if cd else None
    agent_check_res = agent_risk_access(
        ctx,
        spec.command_line,
        workdir=resolved_cd.path if resolved_cd else ctx.agent.workdir,
        extra_allowed_paths=[ctx.agent.tempdir.path],
    )
    if agent_check_res.policy == 'allow':
        return True

    reasons_str = " and ".join(policy.reasons)
    message = f"Confirming on command `{spec.command_line}` because it {reasons_str}."
    if policy.rejection_message:
        message += f"\n{policy.rejection_message}"
    message += f"\n(Risk assessment: {agent_check_res.reason})" if agent_check_res.reason else ""
    if not ctx.agent.display.get_confirm(
        "Allow command?", message,
        title="Command Confirmation" if agent_check_res.policy == 'unsure' else "Dangerous Command Confirmation",
        subtitle=ctx.agent.name,
        default=True if agent_check_res.policy == 'unsure' else False
    ):
        raise RuntimeError(f"Command `{spec.command_line}` was rejected by user confirmation. (risk assessment: {agent_check_res.reason})")

    return policy.allow_unlisted


def _resolve_executable(command: ExecutableSpec, allow_unlisted: bool) -> str | None:
    raw_command = command.value
    if not raw_command:
        raise ValueError("Command must not be empty.")

    if not command.is_bare_command:
        if not allow_unlisted or not command.is_absolute_path:
            raise ValueError("Command must be a bare executable name unless explicitly confirmed as an absolute path.")
        if not command.path.is_file():
            raise ValueError(f"Command '{raw_command}' was not found.")
        return str(command.path)

    executable = shutil.which(raw_command)
    if executable is not None:
        return executable

    # Bare shell builtins such as `cd` are resolved by the invoked shell.
    return None


def _resolve_commands(spec: CommandSpec, allow_unlisted: bool) -> None:
    for command in spec.commands:
        _resolve_executable(command, allow_unlisted=allow_unlisted)


def _soft_kill_process(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        process.terminate()
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def _hard_kill_process(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        process.kill()
        return

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _run_shell_command(
    spec: CommandSpec, 
    timeout: float, 
    cwd: Path, 
    env_overrides: Optional[dict[str, str]]
    ) -> subprocess.CompletedProcess[str]:
    shell_executable = os.environ.get("SHELL")
    envs = os.environ.copy()
    if env_overrides:
        envs.update(env_overrides)
    popen_kwargs = {
        "shell": True,
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": envs,
        "cwd": cwd,
    }
    if shell_executable:
        popen_kwargs["executable"] = shell_executable
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(spec.command_line, **popen_kwargs)  # type: ignore[call-overload]  # nosec B602
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _soft_kill_process(process)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            _hard_kill_process(process)
            stdout, stderr = process.communicate()

        raise RuntimeError(
            f"Command `{spec.command_line}` timed out after {timeout:g}s and was terminated."
        )

    return subprocess.CompletedProcess(
        args=spec.command_line,
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
    )


class CmdExecResult(TypedDict):
    args: str
    stdout: str
    stderr: str
    returncode: int


# Unlisted commands, unsupported shell operators, and absolute command paths still require confirmation.
def shell(
    ctx: ToolCallContext,
    command: str,
    timeout: float = 300,
    cd: Optional[str] = None,
    envs: Optional[dict[str, str]] = None,
) -> CmdExecResult:
    """
    Runs a command and returns its output.
    Commands are always run through the current shell with inherited environment variables.

    The command runs in the current process working directory, and cannot change it persistently.

    `cd` can be used to change the directory before running. 
    Prefer setting `cd` argument instead of using `cd` in the command itself, as it will be rejected by the allowlist.

    `envs` can be used to set environment variables for the command.

    The command is running in a blocking way, will wait until the command finishes before return.
    Commands will be terminated if they exceed the timeout in seconds.

    if need to run non-blocking command, please use `nohup` or `&` operator and confirm the shell operators.
    Do remember to check and cleanup the background processes if run non-blocking, the system won't do it for you.
    """
    spec = _parse_command_spec(command)
    policy = _confirmation_policy(spec)
    allow_unlisted = _confirm_command_execution(ctx, spec, policy, cd=cd)
    _resolve_commands(spec, allow_unlisted=allow_unlisted)

    # Determine workdir with safety validation
    cwd: Path
    if cd is not None:
        resolved = resolve_path(ctx, cd, raise_on_invalid=False)
        if not resolved.in_workdir and not resolved.in_tempdir:
            raise ValueError(
                f"Workdir `{cd}` is not within agent's workdir ({ctx.agent.workdir}) "
                f"nor in any temporary directory."
            )
        cwd = resolved.path
    else:
        cwd = ctx.agent.workdir if ctx else Path.cwd()

    try:
        result = _run_shell_command(
            spec, 
            timeout=timeout, 
            cwd=cwd, 
            env_overrides=envs,
            )
    except KeyboardInterrupt:
        raise RuntimeError(f"Command `{spec.command_line}` was interrupted by user.")

    return CmdExecResult(
        args=spec.command_line,
        stdout=result.stdout.strip(),
        stderr=result.stderr.strip(),
        returncode=result.returncode,
    )


def expose_cmd_tools() -> list[Callable]:
    import rich
    if os.name == "nt":
        rich.print("[Warning] The shell tool is not available on Windows. Skip registering it.")
        return []
    return [shell]