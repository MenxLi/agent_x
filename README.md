# Xun

A mini LLM agent framework with function-based tools and sub-agent spawning.

The core codebase is compact: ~2000 lines (src/xun/*.py), with comprehensive type hints.

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


## Quick Start

Requires Python 3.12+ (PEP 695)

```bash
# 1. Install dependencies
pip install git+https://github.com/MenxLi/xun.git

# 2. Install Playwright browsers (If use default browser tools)
playwright install

# 3. Configure environment variables (see `Configuration` section below)
vim .env

# 4. Run the agent in interactive mode
xun
```

## Usage

**Basic**: Quickly set up an agent with tools:
```python
from xun import setup_agent

def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

agent = setup_agent(tools = [add])
agent.instruct("Add 2 and 3.").execute()
```

**Advanced**: The framework can be flexible and extensible.   
Additional features include:  
- Customize agent setup
- Display customization
- Output validation
- Tool attributes
- Context passing
- Execution hooks
- Sub-agent spawning

Do check out [demo.ipynb](demo.ipynb) for detailed examples. 

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

## Configurations

xun uses environment variables, preferably stored in a `.env` file.

| Variable | Default | Description |
|---|---|---|
| `XUN_OPENAI_BASE_URL` | `http://127.0.0.1:8000/v1` | OpenAI-compatible API endpoint. Default to port 8000 from localhost. |
| `XUN_OPENAI_API_KEY` | *(empty)* | API key. |
| `XUN_OPENAI_MODEL` | *(empty)* | Model identifier. If empty, will auto-detect available models from the API. |
| `XUN_AUTO_CONFIRM` | `false` | Auto-approve actions without prompting. |