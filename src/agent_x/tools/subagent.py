from typing import Optional, Callable
from ..toolbox import ToolBox
from ..agent import Agent
from ..prompt import get_subagent_prompt
import json, uuid

def subagent_run( task: str, name: Optional[str] = None ) -> str:
    """
    Creates an isolated sub-agent to execute complex, multi-step tasks. 
    The new agent holds default toolset (file system, network, command call, etc.) and starts with a blank context.

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

    toolbox = ToolBox().with_defaults()
    agent = Agent(name=name or f"subagent_{str(uuid.uuid4())[:6]}", toolbox=toolbox)
    agent.system(get_subagent_prompt()).instruct(task)
    try:
        return agent.execute(max_iterations=32)
    except Exception as e:
        print(f"Error in sub-agent: {e}")
        return f"[Error in sub-agent: {e}]"

def subagent_run_parallel( tasks: list[str] | str ) -> list[str]:
    """
    Same as `subagent_run`, but designed to run multiple tasks in parallel by creating multiple agents, and return their results as a list.
    Preferably call this if the sub-tasks are independent and can be executed concurrently to save time. 
    Each task will be handled by a separate agent instance, allowing for simultaneous execution.
    (sub-agents will be given random names)

    **Must input a list of tasks as strings.**
    If string is input, it will be treated as Json and parsed into list of strings. 
    If parsing fails, it be treated as a single task and run with `subagent_run`.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if isinstance(tasks, str):
        try:
            tasks = json.loads(tasks)
            if not isinstance(tasks, list) or not all(isinstance(t, str) for t in tasks):
                raise ValueError("Parsed JSON is not a list of strings.")
        except json.JSONDecodeError:
            assert isinstance(tasks, str)
            return [subagent_run(tasks)]

    results: list[str] = [""] * len(tasks)
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_index = {executor.submit(subagent_run, task): i for i, task in enumerate(tasks)}
        for future in as_completed(future_to_index):
            index = future_to_index[future]

            # should not raise, 
            # because subagent_run already catches exceptions and returns error message?
            result = future.result()
            results[index] = result
    return results

def expose_subagent_tools() -> list[Callable]:
    return [subagent_run, subagent_run_parallel]