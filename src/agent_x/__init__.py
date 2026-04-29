
import readline     # import for arrow key support in input()

import argparse
import rich
import rich.panel
from dotenv import load_dotenv
from pathlib import Path

from .tools import expose_worker_tools
from .toolbox import ToolBox
from .config import app_config
from .agent import Agent
from .store import Store

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
            agent.conversation.dump(file_path:=store.next_history_file())
            rich.print(f"[bold green]Conversation history dumped to {file_path}.[/bold green]")
            return ""
        
        elif command == "load":
            if args:
                file_path = Path(args[0])
                if not file_path.exists():
                    rich.print(f"[bold red]File {file_path} does not exist.[/bold red]")
                    return ""
            else:
                store = Store()
                latest_file = store.latest_history_file()
                if latest_file is None:
                    rich.print(f"[bold yellow]No conversation history found.[/bold yellow]")
                    return ""
                file_path = latest_file

            agent.conversation.load(file_path)
            rich.print(f"[bold green]Conversation history loaded from {file_path}.[/bold green]")
            return ""
        
        elif command == "condense":
            agent.condense_conversation()
            return ""

        elif command == "exit":
            print("Bye!")
            exit(0)
        else:
            rich.print(f"[bold red]Unknown command:[/bold red] {command}")
            return ""
    return user_input

def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run the agent.")
    parser.add_argument("instruction", type=str, help="The instruction for the agent.", default="", nargs="?")
    args = parser.parse_args()

    user_input = args.instruction.strip()

    toolbox = ToolBox().with_defaults()
    # top-agent can spawn worker agents to execute tasks.
    toolbox.register_many(expose_worker_tools())
    agent = Agent(toolbox=toolbox)

    if app_config().auto_confirm:
        rich.print(
            rich.panel.Panel(
                "[bold yellow]Auto-confirm is enabled.[/bold yellow]\nPlease be cautious as the agent may execute actions without confirmation, including potentially harmful commands if misused.\nIt's recommended to keep this setting disabled unless you have a specific use case that requires it.",
                title="[bold red]Warning[/bold red]", border_style="red"
                ),
        )

    while True:
        user_input = user_input.strip()
        if not user_input:
            rich.print("[gray]Input (`.help` to show help message).[/gray]")
            user_input = input(">>> ")

        user_input = evaluate_user_input(user_input, agent)
        if not user_input:
            continue
        
        agent.instruct(user_input)
        agent.execute(64)

        user_input = ""