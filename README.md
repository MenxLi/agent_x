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

The core codebase is compact: about 3000 lines in `src/xun/*.py`, with comprehensive type hints.

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

Optionally, run the agent in web mode: 
```sh
# - Build the web frontend (if using the web display)
make web-build
# - Start the web server at current directory
xuns .
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

## CLI

Run `xun` in your terminal to start an interactive session.
You can also pass a prompt as an argument to begin with a specific instruction.
```bash
xun "Write a hello world python script and save it to hello.py"
```

Image attachments are supported in the format of `[image:path_or_url]`. For example:
```
>>> [image:cat.png image:https://example.com/dog.png] compare them.
```

Input `/help` to see the full list of commands.

## Web

`WebDisplay` provides an interactive web interface for the agent. 
It can be used as a chat-based web application, or as a backend for other applications.

```python
from xun import WebDisplay, WebDisplayService, setup_agent

display = WebDisplay(expose_files=True)
agent = setup_agent(display=display, default_tools=True)
service = WebDisplayService().mount("/", display)
service.start(blocking=True)
```

Open any tokenized URL printed at startup. The service exchanges its query token for one HttpOnly cookie scoped to `/`, so the browser can access every mounted display without logging in again. API clients can use `Authorization: Bearer <token>`.

File browsing, upload, download, and deletion are disabled unless `expose_files=True`. 
The agent will start in web mode, and you can access it via the printed URL.

Multiple displays can share one authenticated service. Each mount keeps its own agents, event history, and file policy:

```python
service = WebDisplayService()
service.mount("/research", research_display)
service.mount("/coding", coding_display)
service.start(blocking=True)
```

`display.build_routes()` and `display.build_app()` do not add authentication. Use `WebDisplayService` for the authenticated server, or provide authentication and lifecycle handling in your own ASGI host.

<details>
<summary>Frontend development</summary>
The frontend development command starts both the backend and Vite with Vue DevTools:

```bash
cd web
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Build a production bundle with `npm run build`. See [web/README.md](web/README.md) for connecting the UI to a separately managed backend.
</details>

## Configuration

xun uses environment variables, preferably stored in a `.env` file.

| Variable | Default | Description |
|---|---|---|
| `XUN_OPENAI_BASE_URL` | `http://127.0.0.1:8000/v1` | OpenAI-compatible API endpoint. Default to port 8000 from localhost. |
| `XUN_OPENAI_API_KEY` | *(empty)* | API key. |
| `XUN_OPENAI_MODEL` | *(empty)* | Model identifier. If empty, will auto-detect available models from the API. |
| `XUN_AUTO_CONFIRM` | `false` | Auto-approve actions without prompting. |