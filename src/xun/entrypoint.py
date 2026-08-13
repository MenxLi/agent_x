# import for arrow key support in input()
import readline     # noqa

import argparse, shlex, sys
from pathlib import Path
from typing import Callable, Optional
from pydantic import BaseModel

from .display_abstract import DisplayAbstract
from .display import Display
from .display_web import WebDisplay
from .toolbox import ToolBox
from .agent import Agent
from .store import Store
from .prompt import get_system_prompt
from .command import Command


IMAGE_PREFIX = "image:"


class MessageInstruction(BaseModel):
    content: str
    images: list[str] = []

class CommandInstruction(BaseModel):
    command: str
    args: list[str] = []

Instruction = MessageInstruction | CommandInstruction


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


def get_instruction() -> Instruction:
    while True:
        print("Input (`.help` for help).")
        raw_input = input(">>> ").strip()
        if raw_input:
            return input_to_instruction(raw_input)

def setup_agent(
    name: str = "agent",
    tools: list[Callable] = [],
    default_tools: bool = False,
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
            agent.execute_command(inst.command, ' '.join(inst.args) if inst.args else None)
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
    if task:
        inst = input_to_instruction(task)
    else:
        inst = get_instruction()

    while True:
        _execute_instruction(inst, agent)
        inst = get_instruction()

def non_interactive_session(agent: Agent, instruction: str):
    inst = input_to_instruction(instruction)
    _execute_instruction(inst, agent)

def cli_commands() -> list[Command]:
    def _long_handler(agent: Agent, args: Optional[str]) -> None:
        eol = args.strip() if args else "."
        print(f"Multi-line input mode (end with a line containing only {eol!r}):")
        lines: list[str] = []
        while True:
            line = input("... ")
            if line == eol:
                break
            lines.append(line)
        text = "\n".join(lines)
        if text.strip():
            inst = _parse_message_input(text)
            _execute_instruction(inst, agent)

    def _render_handler(agent: Agent, arguments: Optional[str]) -> None:
        if not arguments: 
            agent.display.error("Please provide a file path to save the rendered HTML.")
            return
        html = agent.conversation.render_history_as_html()
        aim_path = Path(arguments)
        aim_path.write_text(html, encoding="utf-8")
    
    return [
        Command(
            name="long",
            description="Enter multi-line input mode. Optionally specify an end-of-line marker (default is '.').",
            handler=_long_handler
        ),
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
    parser.add_argument("--non-interactive", action="store_true", help="Run in non-interactive mode (default: interactive).")

    args = parser.parse_args()

    user_input = args.instruction.strip()

    if args.persist:
        store = Store()
        persistent_store = store.running_agent_store
    else:
        persistent_store = None

    agent = setup_agent(
        persistent_store=persistent_store, 
        default_tools=True, 
        default_commands=True, 
        display=Display()
        )

    agent.command.register(*cli_commands())
    is_tty = sys.stdin.isatty() and sys.stdout.isatty()
    try:
        if is_tty and not args.non_interactive:
            interactive_session(agent, user_input)
        else:
            if not user_input:
                raise ValueError("Instruction is required in non-interactive mode.")
            non_interactive_session(agent, user_input)
    except:
        raise
    finally:
        agent.finalize()

def main_serve():
    parser = argparse.ArgumentParser(description="Run the agent in web mode.")
    parser.add_argument("--host", type=str, default="localhost", help="Host for the web server (default: localhost).")
    parser.add_argument("--port", type=int, default=18960, help="Port for the web server (default: 18960).")
    parser.add_argument("--token", type=str, default=None, help="Token for accessing the web interface (default: random token).")
    parser.add_argument("--frontend-url", type=str, default=None, help="Frontend URL for the web interface, for DEV (default: None).")
    parser.add_argument("--persist", action="store_true", help="Whether to track the agent's conversation history in the default store.")
    args = parser.parse_args()

    if args.persist:
        store = Store()
        persistent_store = store.running_agent_store
    else:
        persistent_store = None

    agent = setup_agent(
        persistent_store=persistent_store, 
        default_tools=True, 
        default_commands=True, 
        display=WebDisplay()
        )

    try:
        assert isinstance(agent.display, WebDisplay)
        agent.display.start(blocking=True)
    except:
        raise
    finally:
        agent.finalize()