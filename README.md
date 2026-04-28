# Agent X

An autonomous, CLI-based mini LLM agent with built-in tooling for file manipulation, command execution, web search, browser automation, and sub-agent spawning.

## Quick Start

```bash
uv run agent-x "Your task here"
# or enter interactive mode:
uv run agent-x
```

## Features

- **🔧 File System** — list, read, write, and create directories with path-safety checks
- **💻 Command Execution** — run shell commands (allowlisted + interactive confirmation for others)
- **🌐 Web Search** — query Bing via RSS for structured search results
- **🌍 Browser Automation** — fetch rendered pages and convert HTML to markdown (via Playwright)
- **🤖 Sub-Agents** — spawn isolated child agents to handle complex, multi-step tasks
- **🖥️ Rich CLI** — beautiful terminal output with spinner, panels, and syntax highlighting
- **🔁 Interactive Control** — `.help`, `.restart`, `.retry`, `.revise`, `.tools`, `.exit`

## Configuration

Set via environment variables (or `.env` file):

| Variable | Default | Description |
|---|---|---|
| `AGENTX_OPENAI_BASE_URL` | `http://<docker-host-ip>:8000/v1` | OpenAI-compatible API endpoint |
| `AGENTX_OPENAI_API_KEY` | *(empty)* | API key |
| `AGENTX_OPENAI_MODEL` | `/m/Qwen3.6-35B-A3B` | Model identifier |
