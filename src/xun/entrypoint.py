# import for arrow key support in input()
import readline     # noqa

import argparse, sys
from pathlib import Path
from typing import Callable, Optional

from .display_abstract import (
    DisplayAbstract, 
    Instruction,
    CommandInstruction, MessageInstruction, 
)
from .display import Display, input_to_instruction
from .toolbox import ToolBox
from .agent import Agent
from .store import Store
from .prompt import get_system_prompt
from .command import Command

def setup_agent(
    name: str = "agent",
    tools: list[Callable] = [],
    default_tools: bool = True,
    default_system_prompt: bool = True,
    default_commands: bool = True,
    persistent_store: Path | None = None,
    display: DisplayAbstract | None = None,
    ) -> Agent:
    toolbox = ToolBox()
    if default_tools:
        # top-agent can spawn worker agents to execute tasks.
        toolbox.with_defaults().with_subagent_provider()
    if tools:
        toolbox.register(*tools)
    agent = Agent(
        name=name, 
        toolbox=toolbox, 
        persistent_store=persistent_store, 
        display=display or Display()
        )
    if default_system_prompt:
        agent.system(get_system_prompt())
    if default_commands:
        agent.command.with_defaults()
    return agent


def _execute_instruction(inst: Instruction, agent: Agent):
    match inst:
        case CommandInstruction():
            agent.execute_command(inst.command, inst.args)
            if inst.command == "retry":
                agent.execute()

        case MessageInstruction():
            try:
                agent.instruct(inst.content, images=inst.images).execute()
            except ValueError as e:
                agent.display.error(f"Error executing instruction: {e}")
        case _:
            agent.display.error(f"Invalid instruction: {inst}")

def interactive_session(agent: Agent, task = ""):
    display = agent.display
    if task:
        inst = input_to_instruction(task)
    else:
        inst = display.get_instruction()

    while True:
        _execute_instruction(inst, agent)
        inst = display.get_instruction()

def non_interactive_session(agent: Agent, instruction: str):
    inst = input_to_instruction(instruction)
    _execute_instruction(inst, agent)

def cli_commands() -> list[Command]:
    def _render_handler(agent: Agent, arguments: Optional[str]) -> None:
        if not arguments: 
            agent.display.error("Please provide a file path to save the rendered HTML.")
            return
        html = agent.conversation.render_history_as_html()
        aim_path = Path(arguments)
        aim_path.write_text(html, encoding="utf-8")
    
    return [
        Command(
            name="render",
            description="Render the conversation history as HTML, output to the specified file path.",
            handler=_render_handler
        ),
        Command(
            name="exit",
            description="Exit the agent.",
            handler=lambda _: sys.exit(0)
        ),
    ]

def main():

    parser = argparse.ArgumentParser(description="Run the agent.")
    parser.add_argument("instruction", type=str, help="The instruction for the agent.", default="", nargs="?")
    parser.add_argument("--persist", action="store_true", help="Whether to track the agent's conversation history in the default store.")
    parser.add_argument("--non-interactive", action="store_true", help="Run in non-interactive mode, the instruction will be executed directly without interactive command loop. ")
    args = parser.parse_args()

    user_input = args.instruction.strip()

    if args.persist:
        store = Store()
        persistent_store = store.running_agent_store
    else:
        persistent_store = None

    agent = setup_agent(persistent_store=persistent_store)
    agent.command.register(*cli_commands())
    interactive = sys.stdin.isatty() and sys.stdout.isatty() and not args.non_interactive
    if interactive:
        interactive_session(agent, user_input)
    else:
        if not user_input:
            raise ValueError("Instruction is required in non-interactive mode.")
        non_interactive_session(agent, user_input)
