# Xun

A mini LLM agent framework with function-based tools and sub-agent spawning.

<!-- 
Some of the design philosophy:
- Plain functions as tools — no decorators, no classes needed
- Compact core — no heavy abstractions, full type hints
- Sub-agent spawning — built-in multi-agent orchestration
- Event-driven display — pluggable I/O via a simple interface
- Context injection — pass execution context into tools seamlessly 
-->

The core codebase is compact: about 2000 lines in `src/xun/*.py`, with comprehensive type hints.

<!-- <details>
<summary>Why this name?</summary>

**Xun** has multiple relevant meanings in Chinese, all pronounced the same way but written with different characters and have meanings that align well with the purpose of this project:

| Character | Pinyin | Meaning | Why it fits |
|---|---|---|---|
| **寻** | *xún* | seek, search | Agents that seek information and solutions for you |
| **讯** | *xùn* | message, information | Agents that process information and communicate with you |
| **训** | *xùn* | train, instruct | A extensible framework that can be tuned with new tools and instructions |

Pronounced like *shoon*: short, simple, and easy to type.

Also drawn from the author's given name (Meng-Xun), as a personal touch :)

</details>  -->


## Quick Start

Requires Python 3.12+ (PEP 695)

```bash
# 1. Install dependencies
pip install git+https://github.com/MenxLi/xun.git

# 2. Install Playwright browsers (if using the default browser tools)
playwright install

# 3. Configure environment variables (see `Configuration` section below)
vim .env

# 4. Run the agent in interactive mode
xun
```

## Usage


**Basic**: Quickly set up an agent with plain functions as tools — no decorators, no classes needed. 

```python
from xun import setup_agent

def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

agent = setup_agent(tools = [add])
agent.instruct("Add 2 and 3.").execute()
```

**Advanced**: The framework is flexible and extensible.
Additional features are shown in [demo.ipynb](demo.ipynb), including:
- Agent customization
- Display extension
- Output validation
- Context injection
- Tool attributes
- Lifecycle hooks
- Sub-agent spawning
- ...

Do check out [demo.ipynb](demo.ipynb) for detailed examples. 

## Web interface

`WebDisplay` provides an authenticated FastAPI server with streaming chat, image attachments, slash commands, confirmation prompts, and a file browser rooted at each agent's workdir.

```python
from xun import WebDisplay, setup_agent

display = WebDisplay()
agent = setup_agent(display=display, default_tools=True)
display.start(blocking=True)
```

Open the tokenized URL printed at startup. The browser exchanges the query token for an HttpOnly cookie and redirects to a clean URL. API clients can use `Authorization: Bearer <token>`.

An empty `token` generates a secure token, and `base_path` supports multiplexed routes:

```python
display = WebDisplay(
    token="fixed-token",
    base_path="/agents/research",
)
```

The authenticated `/api/capabilities` endpoint returns the model and its canonical capabilities. Image input is enabled when `vision` is present. CLI paths and browser uploads are normalized into URL or base64 image data stored directly in the conversation. The production frontend is compiled into `src/xun/assets/web` and included in the Python package.

For frontend development, run the backend and Vite separately:

```python
display = WebDisplay(frontend_url="http://127.0.0.1:5173")
```

```bash
cd web
npm install
npm run dev
```

Vite proxies `/api` and `/ws` to the backend on port `18960`. Build a production bundle with `npm run build`.

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

## Configuration

xun uses environment variables, preferably stored in a `.env` file.

| Variable | Default | Description |
|---|---|---|
| `XUN_OPENAI_BASE_URL` | `http://127.0.0.1:8000/v1` | OpenAI-compatible API endpoint. Default to port 8000 from localhost. |
| `XUN_OPENAI_API_KEY` | *(empty)* | API key. |
| `XUN_OPENAI_MODEL` | *(empty)* | Model identifier. If empty, will auto-detect available models from the API. |
| `XUN_AUTO_CONFIRM` | `false` | Auto-approve actions without prompting. |