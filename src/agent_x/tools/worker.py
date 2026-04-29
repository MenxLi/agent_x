
from typing import Optional, Callable
from ..toolbox import ToolBox
from ..agent import Agent
import json, uuid

def worker_run( task: str, worker_name: Optional[str] = None ) -> Optional[str]:
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
    agent = Agent(name=worker_name or f"worker_{str(uuid.uuid4())[:6]}", toolbox=toolbox)
    agent.instruct(task)
    try:
        return agent.execute(max_iterations=32)
    except Exception as e:
        print(f"Error in worker agent: {e}")
        return None

def worker_run_parallel( tasks: list[str] | str ) -> list[Optional[str]]:
    """
    Same as `worker_run`, but designed to run multiple tasks in parallel by creating multiple agents, and return their results as a list.
    Preferably call this if the sub-tasks are independent and can be executed concurrently to save time. 
    Each task will be handled by a separate agent instance, allowing for simultaneous execution.
    (worker will be given random names)

    **Must input a list of tasks as strings.**
    If string is input, it will be treated as Json and parsed into list of strings. 
    If parsing fails, it be treated as a single task and run with `worker_run`.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if isinstance(tasks, str):
        try:
            tasks = json.loads(tasks)
            if not isinstance(tasks, list) or not all(isinstance(t, str) for t in tasks):
                raise ValueError("Parsed JSON is not a list of strings.")
        except json.JSONDecodeError:
            assert isinstance(tasks, str)
            return [worker_run(tasks)]

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

def expose_worker_tools() -> list[Callable]:
    return [worker_run, worker_run_parallel]