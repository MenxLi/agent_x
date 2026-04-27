
import argparse
from rich.prompt import Prompt
from dotenv import load_dotenv

from .fs_tools import register_fs_tools
register_fs_tools()

from .cmd_tools import register_cmd_tools
register_cmd_tools()

from .agent_base import AgentBase

def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run the agent.")
    parser.add_argument("instruction", type=str, help="The instruction for the agent.", default="", nargs="?")
    args = parser.parse_args()

    user_input = args.instruction.strip()

    agent = AgentBase()
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