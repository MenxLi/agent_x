# Xun

A mini LLM agent with tooling for file manipulation, command execution, web search, browser automation, and sub-agent spawning.

**This is my personal experimental project**

<!-- 
<details>
<summary>Why this name?</summary>

**Xun** has multiple relevant meanings in Chinese, all pronounced the same way but written with different characters and have meanings that align well with the purpose of this project:

| Character | Pinyin | Meaning | Why it fits |
|---|---|---|---|
| **寻** | *xún* | seek, search | Agents that seek information and solutions for you |
| **讯** | *xùn* | message, information | Agents that process information and communicate with you |
| **训** | *xùn* | train, instruct | A extensible framework that can be tuned with new tools and instructions |

Pronounced like *shoon* — short, simple, and easy to type.

Also drawn from the author's given name (Meng-Xun), as a personal touch to this project :)

</details> 
-->

## Quick Start

Requires Python 3.12+ (PEP 695)

```bash
# 1. Install dependencies
pip install git+https://github.com/MenxLi/xun.git

# 2. Install Playwright browsers
playwright install

# 3. Configure environment variables (see `Configuration` section below)
vim .env

# 4. Run the agent in interactive mode
xun
```

## Usage
Quickly set up an agent with tools:
```python
from xun import setup_agent

def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

agent = setup_agent(
    tools = [add],
    default_tools = False
)
agent.instruct("Add 2 and 3.").execute()
```

More advanced usage with more control, sub-agent spawning and context passing:
```python
from xun import Agent, Display, ToolBox
from xun import ToolCallContext as Context
from datetime import datetime

# context will be removed from schema send to the model, 
# but will be passed to the function when called
def weekday_query(ctx: Context, date: str) -> str:
    """Query the weekday of a given date in YYYY-MM-DD format."""
    ctx.agent.display.info(
        "Inside function, we can access context"
        f"such as agent name: {ctx.agent.name}, tool name: {ctx.tool_name}, "
        f"and the actual context value: {ctx.value}"
        )
    dt = datetime.strptime(date, "%Y-%m-%d")
    return dt.strftime("%A")

def get_subagent(ctx: Context) -> Agent:
    agent = Agent.inherit(ctx.agent)
    agent.toolbox.register(weekday_query)
    agent.system("You are an agent that can perform tasks with tools")
    return agent

agent = Agent(
    toolbox=ToolBox().with_subagent_provider(get_subagent),
    display=Display(),
)
answer = agent.instruct(
    "What day of the week was 2023-06-01? "
    "Call a subagent to findout. "
    "Return the answer in a single word."
    ).execute(context={'foo': 'bar'})
print(f"Answer: {answer}")
```

## CLI

Run `xun` in your terminal to start an interactive session. 
You can also pass a prompt as an argument to run in non-interactive mode, e.g.:
```bash
xun "Write a hello world python script and save it to hello.py"
```

Image attachments are supported in the format of `[image:path_or_url]`. For example:
```
>>> [image:cat.png image:https://example.com/dog.png] compare them.
```

Input `.help` to see the full list of commands.

<details>
<summary>Interactive Commands</summary>

- **`.help`** — Show help message.
- **`.restart`** — Clear conversation history and restart.
- **`.retry`** — Retry the last user message.
- **`.revise`** — Re-input the last user message.
- **`.tools`** — List registered tools and their descriptions.
- **`.config`** — Show current API configuration.
- **`.condense`** — Condense conversation history into a summary to save context.
- **`.dump`** — Dump conversation history to a JSON file.
- **`.load`** — Load conversation history from a JSON file (defaults to the latest).
- **`.history`** — Show conversation history in the terminal.
- **`.exit`** — Exit the program.

</details>

## Configurations

xun uses environment variables, preferably stored in a `.env` file.

| Variable | Default | Description |
|---|---|---|
| `XUN_OPENAI_BASE_URL` | `http://<host-ip>:8000/v1` | OpenAI-compatible API endpoint. Default to port 8000 from localhost. |
| `XUN_OPENAI_API_KEY` | *(empty)* | API key. |
| `XUN_OPENAI_MODEL` | *(empty)* | Model identifier. If empty, will auto-detect available models from the API. |
| `XUN_AUTO_CONFIRM` | `false` | Auto-approve actions without prompting. |