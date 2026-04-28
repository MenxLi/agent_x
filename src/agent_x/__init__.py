
import readline     # import for arrow key support in input()

import argparse
import rich
import rich.panel
from dotenv import load_dotenv

from .tools import *
from .toolbox import ToolBox
from .agent import Agent

def evaluate_user_input(
    user_input: str,
    agent: Agent,
    ) -> str:
    if user_input.startswith("."):
        command = user_input[1:].strip()
        if command == "help":
            panel = rich.panel.Panel.fit(
                """[bold cyan]Available commands:[/bold cyan]
[bold yellow].help[/bold yellow] - Show this help message
[bold yellow].restart[/bold yellow] - Clear conversation history and restart the agent
[bold yellow].retry[/bold yellow] - Retry the last user message (clear to last user message)
[bold yellow].revise[/bold yellow] - Revise the last user message (clear to last user message)
[bold yellow].tools[/bold yellow] - List registered tools
[bold yellow].exit[/bold yellow] - Exit the program""",
                title="[bold blue]Help[/bold blue]",
                border_style="green",
            )
            rich.print(panel)
            return ""
        elif command == "restart":
            agent.clear_last_n_messages(len(agent.messages))
            rich.print("[bold green]Conversation history cleared.[/bold green]")
            return ""
        elif command == "retry":
            msg = agent.pop_last_user_message()
            rich.print(f"[bold green]Cleared to last user message.[/bold green] ({msg[:50] + '...' if len(msg) > 50 else msg})")
            return msg
        elif command == "revise":
            msg = agent.pop_last_user_message()
            rich.print("[bold green]Cleared to last user message.[/bold green]")
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

    toolbox = ToolBox()
    register_fs_tools(toolbox)
    register_cmd_tools(toolbox)
    register_search_tools(toolbox)
    register_browser_tools(toolbox)
    register_worker_tools(toolbox)

    agent = Agent(toolbox=toolbox)
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