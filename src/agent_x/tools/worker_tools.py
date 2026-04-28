
from typing import Optional
from ..toolbox import ToolBox
from ..agent import Agent

def worker_run( task: str ) -> Optional[str]:
    """
    Create a new agent to handle specific tasks, 
    the new agent will have the same toolbox and openai client as the current agent (except initiate new agent).
    Use it when the expected task is isolated and complex (may require multiple steps to complete), and you want to limit context length by starting a new conversation.
    Will return the last message of the agent created or None if the agent exit with error.
    The caller should provide a specific instruction (or tool call necessary) to the new agent to let it know what to do.
    """
    # TODO: now hardcode the tools and openai client

    toolbox = ToolBox()

    from .fs_tools import register_fs_tools
    from .cmd_tools import register_cmd_tools
    from .search_tools import register_search_tools
    from .browser_tools import register_browser_tools
    register_fs_tools(toolbox)
    register_cmd_tools(toolbox)
    register_search_tools(toolbox)
    register_browser_tools(toolbox)

    agent = Agent(name="worker", toolbox=toolbox)
    agent.instruct(task)
    try:
        return agent.execute(max_iterations=32)
    except Exception as e:
        print(f"Error in worker agent: {e}")
        return None

def register_worker_tools(toolbox: ToolBox):
    toolbox.register(worker_run)