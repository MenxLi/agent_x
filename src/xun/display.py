import hashlib, datetime
import readline     # noqa
import threading
import rich
import rich.box
import rich.table
import rich.console
import rich.prompt
import rich.panel
import rich.markdown

from .display_abstract import *
from .config import app_config

class Display(DisplayAbstract):
    def __init__(self):
        self.console = rich.console.Console()
        self.lock = threading.Lock()

    def _print(self, *args, **kwargs):
        with self.lock:
            if isinstance(args[0] if args else None, str):
                self.console.print(f"[dim][{datetime.datetime.now().strftime('%H:%M:%S')}][/dim]", end=" ")
            self.console.print(*args, **kwargs)

    def get_confirm(
        self, 
        prompt: str, 
        message: Optional[str] = None, 
        title: Optional[str] = None, 
        subtitle: str | None = None, 
        default: bool = True
        ) -> bool:
        with self.lock:
            if message:
                _note(self.console, message, title, subtitle)
            return _confirm(self.console, prompt, default)
    
    def get_choice(
        self, 
        prompt: str, 
        choices: list[str], 
        message: str | None = None, 
        title: str | None = None, 
        subtitle: str | None = None, 
        default: str | None = None, 
        allow_extra: bool = False
        ) -> str:
        choices_str = "\n".join(f"  [{i}] {choice}" for i, choice in enumerate(choices, start=1))
        extra_choice_idx = len(choices) + 1 if allow_extra else None
        if allow_extra:
            choices_str += f"\n  [{extra_choice_idx}] Other (enter your own choice)"
        full_msg = f"{message}\n--- Choices ---\n{choices_str}"
        default_idx = choices.index(default) + 1 if default in choices else None
        with self.lock:
            if message:
                _note(self.console, full_msg, title, subtitle)
            choice_idx = _choose_from_int(
                self.console, 
                prompt = prompt, 
                n_choices=len(choices) + (1 if allow_extra else 0),
                default=default_idx)
            if allow_extra and choice_idx == extra_choice_idx:
                extra_choice = rich.prompt.Prompt.ask("Enter your choice")
                return extra_choice
            return choices[choice_idx - 1]
        

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
            case UserMessageEvent(): ... # Shown by input
            case UserCommandEvent(): ... # Shown by input
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
        return default

def _choose_from_int(
    console: rich.console.Console, 
    prompt: str, 
    n_choices: int,
    default: Optional[int] = None,
    ) -> int:
    cfg = app_config()
    if default is None:
        default = 1
    if not cfg.auto_confirm:
        ret = rich.prompt.Prompt.ask(prompt, choices=list(map(str, range(1, n_choices + 1))), default=str(default))
        console.print()
        return int(ret)
    else:
        return default

def _note(console: rich.console.Console, message: str, title: Optional[str] = "Note", subtitle: Optional[str] = None) -> None:
    panel = rich.panel.Panel(message, border_style="yellow", title=f"[bold yellow]{title}[/bold yellow]" if title else None, subtitle=f"[dim]{subtitle}[/dim]" if subtitle else None)
    console.print(panel)

class NullDisplay(DisplayAbstract):
    def get_choice( self, *args, **kwargs) -> str:
        raise NotImplementedError("NullDisplay does not support get_choice.")

    def on_event(self, event: DisplayEvent):
        pass