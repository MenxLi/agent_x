# Agent X

An autonomous, CLI-based mini LLM agent with tooling for file manipulation, command execution, web search, browser automation, and sub-agent spawning.

## Quick Start

```bash
# 1. Install dependencies
pip install .

# 2. Install Playwright browsers
playwright install

# 3. Configure environment variables (see `Configuration` section below)
# 4. Run the agent
agentx
```

## Features

- **🔧 File System** — Read, write, list, and manage files securely within the working directory.
- **💻 Command Execution** — Run shell commands with an allowlist and safety checks.
- **🌐 Web Search** — Search the web and retrieve structured results.
- **🌍 Browser Automation** — Fetch rendered pages and convert HTML to markdown.
- **🤖 Sub-Agents** — Spawn isolated child agents for complex, multi-step tasks.
- **🖥️ Rich CLI** — Beautiful terminal output with spinners, panels, and syntax highlighting.

## Interactive Commands

The agent supports dot-commands for control.  
Input `.help` to see the full list of commands.

<details>
<summary>View all CLI commands</summary>

- **`.help`** — Show help message.
- **`.restart`** — Clear conversation history and restart.
- **`.retry`** — Retry the last user message (clears history up to the last message).
- **`.revise`** — Re-input the last user message (clears history up to the last message).
- **`.tools`** — List registered tools and their descriptions.
- **`.config`** — Show current API configuration.
- **`.condense`** — Condense conversation history into a summary to save context.
- **`.dump`** — Dump conversation history to a JSON file.
- **`.load`** — Load conversation history from a JSON file (defaults to the latest).
- **`.exit`** — Exit the program.

</details>

## Configuration

Agent X uses environment variables, preferably stored in a `.env` file.

| Variable | Default | Description |
|---|---|---|
| `AGENTX_OPENAI_BASE_URL` | `http://<host-ip>:8000/v1` | OpenAI-compatible API endpoint. Default to auto detected host IP from docker container. |
| `AGENTX_OPENAI_API_KEY` | *(empty)* | API key. Leave empty for local models. |
| `AGENTX_OPENAI_MODEL` | `/m/Qwen3.6-35B-A3B` | Model identifier. |