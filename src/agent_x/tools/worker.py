
from typing import Optional
from ..toolbox import ToolBox
from ..agent import Agent

def worker_run( task: str ) -> Optional[str]:
    """
    Creates an isolated sub-agent to execute complex, multi-step tasks. The new agent inherits the current agent's toolbox and OpenAI client, but excludes the agent-creation tool to prevent recursion. 

    Use this when:
    • The task is self-contained but requires multiple steps or heavy reasoning.
    • You need to isolate execution to avoid bloating the main conversation's context window.
    • The task does not require frequent back-and-forth with the parent agent.

    Input: A clear, self-contained instruction or tool directive specifying exactly what the new agent should do.
    Output: Returns the new agent's final output message upon successful completion, or `None` if it exits prematurely or encounters an error.

    Notes:
    • The new agent starts with a blank context and cannot access the parent conversation history unless explicitly included in the instruction.
    • Prefer instructing the new agent to return results directly in its final message. File I/O can also be used for larger outputs or intermediate results when necessary, but should explicitly be mentioned in the instruction.
    """
    # TODO: now hardcode the tools and openai client

    toolbox = ToolBox()

    from .fs import register_fs_tools
    from .cmd import register_cmd_tools
    from .search import register_search_tools
    from .browser import register_browser_tools
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

def worker_run_parallel( tasks: list[str] ) -> list[Optional[str]]:
    """
    Same as `worker_run`, but designed to run multiple tasks in parallel by creating multiple agents, and return their results as a list.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: list[Optional[str]] = [None] * len(tasks)
    with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        future_to_index = {executor.submit(worker_run, task): i for i, task in enumerate(tasks)}
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                result = future.result()
                results[index] = result
            except Exception as e:
                print(f"Error in worker agent for task `{tasks[index]}`: {e}")
                results[index] = None
    return results

def register_worker_tools(toolbox: ToolBox):
    toolbox.register(worker_run)
    toolbox.register(worker_run_parallel)