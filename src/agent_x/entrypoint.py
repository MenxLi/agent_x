# import for arrow key support in input()
import readline     # noqa

import argparse
import rich
import rich.panel
from dotenv import load_dotenv
from pathlib import Path
import shlex
from typing import Callable
from dataclasses import dataclass, field

from .toolbox import ToolBox
from .agent import Agent
from .store import Store
from .prompt import get_system_prompt

@dataclass
class MessageInstruction:
    content: str

@dataclass
class CommandInstruction:
    command: str
    args: list[str] = field(default_factory=list)

Instruction = MessageInstruction | CommandInstruction

def input_to_instruction(raw_input: str) -> Instruction:
    if raw_input.startswith("."):
        raw_command = raw_input[1:].strip()
        command = raw_command.split()[0] if raw_command else ""
        args = shlex.split(raw_command)[1:] if raw_command else []
        return CommandInstruction(command=command, args=args)
    else:
        return MessageInstruction(content=raw_input)
def get_instruction() -> Instruction:
    while True:
        rich.print("[gray]Input (`.help` to show help message).[/gray]")
        raw_input = input(">>> ").strip()
        if raw_input:
            break
    return input_to_instruction(raw_input)


REPL_HELP_MSG = """\
[bold cyan]Available commands:[/bold cyan]
[bold yellow].help[/bold yellow] - Show this help message
[bold yellow].restart[/bold yellow] - Clear conversation history and restart the agent
[bold yellow].retry[/bold yellow] - Retry the last user message (clear to last user message)
[bold yellow].revise[/bold yellow] - Re-input the last user message (clear to last user message)
[bold yellow].tools[/bold yellow] - List registered tools
[bold yellow].config[/bold yellow] - Show current configuration
[bold yellow].condense[/bold yellow] - Condense conversation history to reduce token usage
[bold yellow].dump[/bold yellow] - Dump conversation history to a store
[bold yellow].load[/bold yellow] - Load conversation history from latest store or specified store
[bold yellow].history[/bold yellow] - Show conversation history in the terminal
[bold yellow].exit[/bold yellow] - Exit the program\
"""
def evaluate_command(instruction: CommandInstruction, agent: Agent):
    match instruction.command:
        case "help":
            panel = rich.panel.Panel.fit(
                REPL_HELP_MSG, 
                title="[bold blue]Help[/bold blue]",
                border_style="green",
            )
            rich.print(panel)

        case "restart":
            agent.conversation.clear()
            rich.print("[bold green]Conversation history cleared.[/bold green]")

        case "retry":
            records = agent.conversation.pop_from_last_user_message()
            assert records and isinstance(records, list) and len(records) > 0 and isinstance(records[0], dict) and records[0].get("role") == "user"
            msg = records[0]["content"]
            rich.print(f"[bold green]Cleared to last user message.[/bold green] ({msg[:50] + '...' if len(msg) > 50 else msg})")

        case "revise":
            agent.conversation.pop_from_last_user_message(inclusive=False)
            rich.print("[bold green]Cleared to last user message.[/bold green]")

        case "config":
            config = agent.app_config
            rich.print(config.dict())

        case "tools":
            tools = agent.toolbox.list_tools()
            if not tools:
                rich.print("[bold yellow]No tools registered.[/bold yellow]")
                return
            panel = rich.panel.Panel.fit(
                "\n".join([f"[bold cyan]{tool.name}[/bold cyan]: {tool.description}" for tool in tools]),
                title="[bold blue]Registered Tools[/bold blue]",
                border_style="green",
            )
            rich.print(panel)

        case "dump":
            store = Store()
            agent.dump(aim_dir:=store.next_history_store())
            rich.print(f"[bold green]Conversation history dumped to {aim_dir}[/bold green]")

        case "load":
            if instruction.args:
                aim_dir = Path(instruction.args[0])
                if not aim_dir.exists():
                    rich.print(f"[bold red]File {aim_dir} does not exist.[/bold red]")
                    return
                if not aim_dir.is_dir():
                    rich.print(f"[bold red]{aim_dir} is not a directory.[/bold red]")
                    return
            else:
                store = Store()
                latest_dir = store.latest_history_store()
                if latest_dir is None:
                    rich.print(f"[bold yellow]No conversation history found.[/bold yellow]")
                    return
                aim_dir = latest_dir
            agent.load(aim_dir)
            rich.print(f"[bold green]Conversation history loaded from {aim_dir}[/bold green]")

        case "condense":
            agent.condense_conversation()

        case "history":
            agent.renderer.render_history(agent)

        case "exit":
            print("Bye!")
            exit(0)

        case _:
            rich.print(f"[bold red]Unknown command:[/bold red] {instruction.command}")

def setup_agent(
    name: str = "agent",
    tools: list[Callable] = [],
    default_tools: bool = True,
    default_system_prompt: bool = True,
    persistent_store: Path | None = None,
    ) -> Agent:
    toolbox = ToolBox()
    if default_tools:
        # top-agent can spawn worker agents to execute tasks.
        toolbox.with_defaults().with_subagent_provider()
    if tools:
        toolbox.register_many(tools)
    agent = Agent(name=name, toolbox=toolbox, persistent_store=persistent_store)
    if default_system_prompt:
        agent.system(get_system_prompt())
    return agent

def interactive_session(agent: Agent, task = ""):
    while True:
        user_input = input_to_instruction(task) if task else get_instruction()
        task = ""  # only use the initial task once

        if isinstance(user_input, CommandInstruction):
            evaluate_command(user_input, agent)
            continue
        
        agent.instruct(user_input.content).execute()

def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run the agent.")
    parser.add_argument("instruction", type=str, help="The instruction for the agent.", default="", nargs="?")
    parser.add_argument("--persist", action="store_true", help="Whether to track the agent's conversation history in the default store.")
    args = parser.parse_args()

    user_input = args.instruction.strip()

    if args.persist:
        store = Store()
        persistent_store = store.running_agent_store
    else:
        persistent_store = None

    agent = setup_agent(persistent_store=persistent_store)
    interactive_session(agent, user_input)

__all__ = ["main", "setup_agent", "interactive_session"]