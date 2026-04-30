# import for arrow key support in input()
import readline     # noqa

import argparse
import rich
import rich.panel
from dotenv import load_dotenv
from pathlib import Path
from typing import Callable

from .tools import expose_worker_tools
from .toolbox import ToolBox
from .config import app_config
from .agent import Agent
from .store import Store
from .prompt import SYSTEM_PROMPT

def evaluate_user_input(
    user_input: str,
    agent: Agent,
    ) -> str:
    if user_input.startswith("."):
        raw_command = user_input[1:].strip()
        command = raw_command.split()[0] if raw_command else ""
        args = raw_command.split()[1:] if raw_command else []

        if command == "help":
            panel = rich.panel.Panel.fit(
                """[bold cyan]Available commands:[/bold cyan]
[bold yellow].help[/bold yellow] - Show this help message
[bold yellow].restart[/bold yellow] - Clear conversation history and restart the agent
[bold yellow].retry[/bold yellow] - Retry the last user message (clear to last user message)
[bold yellow].revise[/bold yellow] - Re-input the last user message (clear to last user message)
[bold yellow].tools[/bold yellow] - List registered tools
[bold yellow].config[/bold yellow] - Show current configuration
[bold yellow].condense[/bold yellow] - Condense conversation history to reduce token usage
[bold yellow].dump[/bold yellow] - Dump conversation history to a json file
[bold yellow].load[/bold yellow] - Load conversation history from a json file (default to the latest one in the store)
[bold yellow].history[/bold yellow] - Show conversation history in the terminal
[bold yellow].exit[/bold yellow] - Exit the program""",
                title="[bold blue]Help[/bold blue]",
                border_style="green",
            )
            rich.print(panel)
            return ""

        elif command == "restart":
            agent.conversation.clear()
            rich.print("[bold green]Conversation history cleared.[/bold green]")
            return ""

        elif command == "retry":
            records = agent.conversation.pop_from_last_user_message()
            assert records and isinstance(records, list) and len(records) > 0 and isinstance(records[0], dict) and records[0].get("role") == "user"
            msg = records[0]["content"]
            rich.print(f"[bold green]Cleared to last user message.[/bold green] ({msg[:50] + '...' if len(msg) > 50 else msg})")
            return msg

        elif command == "revise":
            agent.conversation.pop_from_last_user_message(inclusive=False)
            rich.print("[bold green]Cleared to last user message.[/bold green]")
            return ""

        elif command == "config":
            config = agent.app_config
            rich.print(config.dict())
            return ""

        elif command == "tools":
            tools = agent.toolbox.list_tools()
            if not tools:
                rich.print("[bold yellow]No tools registered.[/bold yellow]")
                return ""
            panel = rich.panel.Panel.fit(
                "\n".join([f"[bold cyan]{tool.name}[/bold cyan]: {tool.description}" for tool in tools]),
                title="[bold blue]Registered Tools[/bold blue]",
                border_style="green",
            )
            rich.print(panel)
            return ""

        elif command == "dump":
            store = Store()
            agent.dump(aim_dir:=store.next_history_store())
            rich.print(f"[bold green]Conversation history dumped to {aim_dir}[/bold green]")
            return ""
        
        elif command == "load":
            if args:
                aim_dir = Path(args[0])
                if not aim_dir.exists():
                    rich.print(f"[bold red]File {aim_dir} does not exist.[/bold red]")
                    return ""
                if not aim_dir.is_dir():
                    rich.print(f"[bold red]{aim_dir} is not a directory.[/bold red]")
                    return ""
            else:
                store = Store()
                latest_dir = store.latest_history_store()
                if latest_dir is None:
                    rich.print(f"[bold yellow]No conversation history found.[/bold yellow]")
                    return ""
                aim_dir = latest_dir

            agent.load(aim_dir)
            rich.print(f"[bold green]Conversation history loaded from {aim_dir}[/bold green]")
            return ""
        
        elif command == "condense":
            agent.condense_conversation()
            return ""
        
        elif command == "history":
            agent.renderer.render_history()
            return ""

        elif command == "exit":
            print("Bye!")
            exit(0)
        else:
            rich.print(f"[bold red]Unknown command:[/bold red] {command}")
            return ""
    return user_input

def setup_agent(
    name: str = "agent",
    tools: list[Callable] = [],
    default_tools: bool = True,
    persistent_store: Path | None = None,
    ) -> Agent:
    toolbox = ToolBox()
    if default_tools:
        # top-agent can spawn worker agents to execute tasks.
        toolbox.register_many(expose_worker_tools())
        toolbox.with_defaults()
    if tools:
        toolbox.register_many(tools)
    agent = Agent(name=name, toolbox=toolbox, persistent_store=persistent_store)
    return agent

def interactive_session(agent: Agent, instruction = ""):
    if app_config().auto_confirm:
        rich.print(
            rich.panel.Panel(
                "[bold yellow]Auto-confirm is enabled.[/bold yellow]\nPlease be cautious as the agent may execute actions without confirmation, including potentially harmful commands if misused.\nIt's recommended to keep this setting disabled unless you have a specific use case that requires it.",
                title="[bold red]Warning[/bold red]", border_style="red"
                ),
        )

    user_input = instruction.strip()
    while True:
        user_input = user_input.strip()
        if not user_input:
            rich.print("[gray]Input (`.help` to show help message).[/gray]")
            user_input = input(">>> ")

        user_input = evaluate_user_input(user_input, agent)
        if not user_input:
            continue
        
        agent.instruct(user_input)
        agent.execute()

        user_input = ""

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

    agent = setup_agent(persistent_store=persistent_store).system(SYSTEM_PROMPT)
    interactive_session(agent, user_input)

__all__ = ["main", "setup_agent", "interactive_session"]