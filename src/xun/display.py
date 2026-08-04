import hashlib, datetime
from selectors import DefaultSelector, EVENT_READ
import readline     # noqa
import sys, time, threading
import shlex
import rich
import rich.box
import rich.table
import rich.console
import rich.prompt
import rich.panel
import rich.markdown

from .display_abstract import *
from .config import app_config


IMAGE_PREFIX = "image:"

def _parse_image_block(image_block: str) -> list[str] | None:
    images = []
    for token in shlex.split(image_block):
        if not token.startswith(IMAGE_PREFIX) or len(token) <= len(IMAGE_PREFIX):
            return None
        images.append(token[len(IMAGE_PREFIX):])
    return images or None

def _parse_message_input(raw_input: str) -> MessageInstruction:
    content = raw_input.strip()
    if not content.startswith("["):
        return MessageInstruction(content=raw_input)
    image_block_end = content.find("]")
    if image_block_end < 0:
        raise ValueError("Invalid image syntax: missing closing ']'.")
    image_block = content[1:image_block_end].strip()
    images = _parse_image_block(image_block)
    if images is None:
        return MessageInstruction(content=raw_input)
    return MessageInstruction(content=content[image_block_end + 1:].strip(), images=images)

def input_to_instruction(raw_input: str) -> Instruction:
    if raw_input.startswith("."):
        raw_command = raw_input[1:].strip()
        command = raw_command.split()[0] if raw_command else ""
        args = shlex.split(raw_command)[1:] if raw_command else []
        return CommandInstruction(command=command, args=args)
    if raw_input.startswith("\\."):
        raw_input = raw_input[1:]
    return _parse_message_input(raw_input)

class Display(DisplayAbstract):
    def __init__(self):
        self.console = rich.console.Console()
        self.lock = threading.Lock()

    def _print(self, *args, **kwargs):
        with self.lock:
            if isinstance(args[0] if args else None, str):
                self.console.print(f"[dim][{datetime.datetime.now().strftime('%H:%M:%S')}][/dim]", end=" ")
            self.console.print(*args, **kwargs)

    def get_instruction(self) -> Instruction:
        while True:
            self._print("[gray]Input (`.help` for help).[/gray]")
            with self.lock:
                raw_input = input(">>> ").strip()
            if raw_input:
                return input_to_instruction(raw_input)

    def get_confirm(self, prompt: str, message: Optional[str] = None, title: Optional[str] = None, subtitle: str | None = None, default: bool = True) -> bool:
        with self.lock:
            if message:
                _note(self.console, message, title, subtitle)
            return _confirm(self.console, prompt, default)

    def on_event(self, event: DisplayEvent):
        match event.event:
            case ShowHelpEvent(): self._show_help(event)
            case ShowHistoryEvent(): self._show_history(event)
            case ToolCallEvent(): self._show_tool_call(event)
            case ModelWorkingEvent(): self._show_model_working(event)
            case ModelMessageEvent(): self._show_model_message(event)
            case ToolResultEvent(): self._show_tool_result(event)
            case InfoEvent(): self._show_info(event)
            case WarningEvent(): self._show_warning(event)
            case ErrorEvent(): self._show_error(event)
            case _: self._unhandled(event)

    def _show_help(self, event: DisplayEvent[ShowHelpEvent]) -> None:
        help_event = event.event
        table = rich.table.Table.grid(expand=True)
        table.add_column("Command", style="bold cyan", no_wrap=True)
        table.add_column("Description", style="dim")
        for cmd in help_event.commands:
            table.add_row(f"[bold white] .{cmd.name}[/bold white]", cmd.description)
        self._print(table)

    def _show_history(self, event: DisplayEvent[ShowHistoryEvent]) -> None:
        history = event.event.history
        if not history:
            self._print(rich.panel.Panel("[dim]No history yet.[/dim]", title="Conversation History", border_style="green", box=rich.box.ROUNDED, padding=(0, 1)))
            return
        sub_panels = []
        for i, record in enumerate(history):
            if not record['content']:
                continue
            color = self._role_color(record["role"])
            row = rich.table.Table.grid(expand=True)
            row.add_column(style=f"bold {color}", width=10)
            row.add_column(ratio=1)
            row.add_row(record["role"], rich.markdown.Markdown(record["content"], code_theme="monokai", hyperlinks=True))
            sub_panels.append(rich.panel.Panel(row, border_style=color, box=rich.box.ROUNDED, padding=(0, 0)))
        self._print(rich.panel.Panel(rich.console.Group(*sub_panels), title="Conversation History", subtitle=f"[dim]{len(sub_panels)} msgs[/dim]", box=rich.box.ROUNDED, padding=(0, 1)))

    def _show_tool_call(self, event: DisplayEvent[ToolCallEvent]) -> None:
        assert event.agent is not None
        ev = event.event
        tool_id = hashlib.sha1(ev.tool_call_id.encode()).hexdigest()[:6]
        self._print(f":wrench: {event.agent.name} [dim]{tool_id}[/dim] [bold green]{ev.tool_name}[/bold green]({self._arg_str(ev.args)})")

    def _show_model_working(self, event: DisplayEvent[ModelWorkingEvent]) -> None:
        assert event.agent is not None
        ev = event.event
        msg = f":green_circle: {event.agent.name} running"
        if ev.remaining_iterations and ev.remaining_iterations < 8:
            msg += f" (max {ev.remaining_iterations})"
        self._print(msg)

    def _show_model_message(self, event: DisplayEvent[ModelMessageEvent]) -> None:
        assert event.agent is not None
        ev = event.event
        self._print(rich.panel.Panel(rich.markdown.Markdown(ev.content, code_theme="monokai", hyperlinks=True), title=f" {event.agent.name} ", border_style="blue"))

    def _show_warning(self, event: DisplayEvent[WarningEvent]) -> None:
        self._print(f":yellow_circle: {event.event.message}")

    def _show_error(self, event: DisplayEvent[ErrorEvent]) -> None:
        self._print(f":red_circle: {event.event.message}")

    def _show_tool_result(self, event: DisplayEvent[ToolResultEvent]) -> None:
        ev = event.event
        if isinstance(ev.result, dict) and "error" in ev.result:
            self._print(f":red_circle: tool error: {ev.result['error']}")

    def _show_info(self, event: DisplayEvent[InfoEvent]) -> None:
        self._print(f":information_source: {event.event.message}")

    def _unhandled(self, event: DisplayEvent) -> None:
        self._print(f":question: Unhandled event")

    @staticmethod
    def _role_color(role: str) -> str:
        return {
            "system": "magenta",
            "user": "cyan",
            "assistant": "green",
            "tool": "yellow",
        }.get(role, "white")

    @staticmethod
    def _arg_str(args: JsonType) -> str:
        if isinstance(args, (str, int, float, bool, type(None))):
            return repr(args)
        if isinstance(args, list):
            return "[" + ", ".join(Display._arg_str(item) for item in args) + "]"
        assert isinstance(args, dict)
        pairs = []
        for k, v in args.items():
            if isinstance(v, str):
                v = ("'" + v[:47] + "...'") if len(v) > 50 else ("'" + v + "'")
            pairs.append(f"[bold yellow]{k}[/bold yellow]: {v}")
        return ", ".join(pairs)

def _confirm(console: rich.console.Console, prompt: str, default: bool = False) -> bool:
    cfg = app_config()
    if not cfg.auto_confirm:
        ret = rich.prompt.Confirm.ask(prompt, default=default)
        console.print()
        return ret
    else:
        if cfg.auto_confirm_timeout <= 0 or not sys.stdin.isatty():
            return default
        def parse_response(response: str) -> bool | None:
            n = response.strip().lower()
            if n in {"", "y", "yes"}:
                return n == "" or default
            if n in {"n", "no"}:
                return False
            return None
        selector = DefaultSelector()
        try:
            selector.register(sys.stdin, EVENT_READ)
        except (ValueError, OSError, PermissionError):
            return default
        deadline = time.monotonic() + cfg.auto_confirm_timeout
        suffix = "[Y/n]" if default else "[y/N]"
        try:
            while True:
                remaining = deadline - time.monotonic() + 0.01
                if remaining <= 0:
                    console.print()
                    return default
                console.print(f"{prompt} {suffix} (in {max(1, int(remaining))}s): ", end="", markup=False, soft_wrap=True)
                if not selector.select(remaining):
                    console.print()
                    return default
                response = sys.stdin.readline()
                if response == "":
                    console.print()
                    return default
                approved = parse_response(response)
                if approved is not None:
                    return approved
                console.print("[prompt.invalid]Please enter Y or N[/prompt.invalid]")
        finally:
            selector.close()

def _note(console: rich.console.Console, message: str, title: Optional[str] = "Note", subtitle: Optional[str] = None) -> None:
    panel = rich.panel.Panel(message, border_style="yellow", title=f"[bold yellow]{title}[/bold yellow]" if title else None, subtitle=f"[dim]{subtitle}[/dim]" if subtitle else None)
    console.print(panel)