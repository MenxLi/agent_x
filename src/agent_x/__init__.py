
import readline     # import for arrow key support in input()

import argparse
from rich.prompt import Prompt
from dotenv import load_dotenv

from .tools import *
from .toolbox import ToolBox
from .agent import Agent

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

    agent = Agent(toolbox=toolbox)
    while True:
        if not user_input:
            user_input = Prompt.ask(
                "Input (`.exit` to quit)",
                ).strip()
        
        if user_input == ".exit":
            print("Bye!")
            break
        
        agent.instruct(user_input)
        agent.execute(64)

        user_input = ""