"""
Modified from: 
https://github.com/czerwiakowskim/qwen-toolcall-fixer/blob/main/middleware.py

Qwen Tool-Call Fixer Middleware
===============================
A transparent OpenAI-compatible proxy that fixes multiple Qwen3.5 tool-call bugs:
- Tool calls emitted inside reasoning_content instead of the tool_calls field
- Malformed tool-call XML (merged tags, wrong wrappers, bare function tags, etc.)
- Empty tool_calls arrays that crash clients
- Reasoning-only responses that stall agentic loops

Sits between any OpenAI-compatible client and an upstream API (LiteLLM, vLLM, etc.).
Handles both streaming (SSE) and non-streaming responses.

See README.md for full documentation.
"""

import os
import re
import json
import uuid
import logging
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
EMIT_NOOP_ON_ORPHAN = os.environ.get("EMIT_NOOP_ON_ORPHAN", "false").lower() in ("true", "1", "yes")

logging.basicConfig(
    level=getattr(logging, "ERROR", logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("qwen-toolcall-fixer")

# ---------------------------------------------------------------------------
# Tool-call extraction from reasoning content
#
# Two-tier approach:
#   1. STRICT regex – fast path for well-formed XML
#   2. FUZZY parser – fallback for the many ways Qwen mangles the tags
#
# Known malformation patterns from Qwen3.5:
#   a) Merged opening:  <tool_call>function=edit>  (missing < before function)
#   b) Wrapper param:   <parameter=parameters><parameter=filePath>…  (nested)
#   c) Missing </function> or </tool_call> closing tags
#   d) Missing < or > on individual tags
#   e) Extra whitespace / newlines anywhere
#   f) Wrong outer tag:  <tools> instead of <tool_call>
#   g) Bare function tag: <read> instead of <function=read>
#   h) Mismatched closers: <tools>…</tool_call> or <read>…</function>
# ---------------------------------------------------------------------------

# ---- Strict patterns (well-formed) ----
STRICT_TOOL_CALL = re.compile(
    r"<tool_call>\s*<function=(\w[\w.-]*)>(.*?)</function>\s*</tool_call>",
    re.DOTALL,
)
# Leaf-only: won't match wrapper params containing nested <parameter= tags
STRICT_PARAM = re.compile(
    r"<parameter=(\w[\w.-]*)>\s*((?:(?!<parameter=)[\s\S])*?)\s*</parameter>",
    re.DOTALL,
)

# ---- Fuzzy patterns (fallback) ----
# Outer opening: <tool_call…> or <tools> (Qwen sometimes uses wrong tag name)
_OUTER_OPEN = r"(?:<tool_call[^>]*>|<tools\s*>)"
# Outer closing: </tool_call> or </tools> (either may appear regardless of opener)
_OUTER_CLOSE = r"(?:</tool_call>|</tools>)"

FUZZY_BLOCK_FULL = re.compile(
    _OUTER_OPEN + r"[\s\S]+?" + _OUTER_CLOSE,
    re.DOTALL,
)
FUZZY_BLOCK_INNER = re.compile(
    _OUTER_OPEN + r"([\s\S]+?)" + _OUTER_CLOSE,
    re.DOTALL,
)
# Same but anchored to end-of-string for unclosed blocks
FUZZY_BLOCK_FULL_EOT = re.compile(
    _OUTER_OPEN + r"[\s\S]+$",
    re.DOTALL,
)
FUZZY_BLOCK_INNER_EOT = re.compile(
    _OUTER_OPEN + r"([\s\S]+)$",
    re.DOTALL,
)
# Function name – three strategies in priority order:
#   1) <function=name> or function=name>  (attribute-style, possibly missing <)
#   2) <name>  (bare tag before first <parameter=)   — Qwen sometimes emits this
FUZZY_FUNC_NAME_ATTR = re.compile(r"(?:<\s*)?function\s*=\s*(\w[\w.-]*)\s*>?")
# Bare tag: a tag that is NOT parameter, function, tool_call, tools, or a closing tag
# and appears before <parameter=.  We search only the first few lines of the block.
FUZZY_FUNC_NAME_BARE = re.compile(
    r"<(\w[\w.-]*)>",
)
_BARE_TAG_SKIP = frozenset({
    "parameter", "function", "tool_call", "tools", "tool",
    "system-reminder", "system", "instructions",
})
# Parameter – LEAF-only: value must NOT contain another <parameter= tag.
# This uses a negative lookahead at each char so the regex naturally skips
# wrapper params like <parameter=parameters> and only matches innermost ones.
FUZZY_PARAM = re.compile(
    r"<parameter=(\w[\w.-]*)>\s*((?:(?!<parameter=)[\s\S])*?)\s*</parameter>",
    re.DOTALL,
)

# Quick presence check – does the text even look like it has a tool call?
HAS_TOOL_CALL_HINT = re.compile(r"<tool_call|tool_call>|<function=|<tools>", re.IGNORECASE)
# Weaker hint: orphaned <parameter= tags without any wrapper – not recoverable but worth logging
HAS_ORPHAN_PARAM_HINT = re.compile(r"<parameter=\w", re.IGNORECASE)


def _parse_param_value(raw: str):
    """Try to parse a parameter value as JSON (number, bool, null), fall back to string."""
    stripped = raw.strip()
    if stripped in ("true", "false", "null") or stripped.lstrip("-").replace(".", "", 1).isdigit():
        try:
            return json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            pass
    return raw.strip()


def _extract_leaf_params(block: str) -> dict:
    """
    Extract parameter key-value pairs from a block, handling Qwen's nesting bug.

    The FUZZY_PARAM regex uses a negative lookahead so it naturally matches only
    leaf (innermost) parameters — wrapper params like <parameter=parameters> that
    contain nested <parameter= tags are skipped by the regex itself.
    """
    params: dict = {}
    for pm in FUZZY_PARAM.finditer(block):
        params[pm.group(1)] = _parse_param_value(pm.group(2))
    return params


def _make_tool_call_obj(func_name: str, arguments: dict) -> dict:
    return {
        "id": f"chatcmpl-tool-{uuid.uuid4().hex[:16]}",
        "type": "function",
        "function": {
            "name": func_name,
            "arguments": json.dumps(arguments),
        },
    }


_NOOP_MESSAGE = (
    "echo '[qwen-toolcall-fixer] Your previous tool call was malformed and could "
    "not be parsed. The XML structure was missing outer <tool_call> or <function=> "
    "tags. Please retry your tool call with correct formatting.'"
)


def _make_noop_tool_call() -> dict:
    """
    Create a synthetic bash tool call that prints a diagnostic warning.

    The agent harness (Claude Code / OpenCode) will execute it, producing
    output the model sees on the next turn — giving it a chance to
    self-correct instead of silently stalling.
    """
    return _make_tool_call_obj("bash", {"command": _NOOP_MESSAGE})


def _extract_strict(text: str) -> tuple[str, list[dict]]:
    """Tier 1: strict regex for well-formed tool-call XML."""
    tool_calls: list[dict] = []
    for match in STRICT_TOOL_CALL.finditer(text):
        func_name = match.group(1)
        params_block = match.group(2)
        arguments = {}
        for pm in STRICT_PARAM.finditer(params_block):
            arguments[pm.group(1)] = _parse_param_value(pm.group(2))
        tool_calls.append(_make_tool_call_obj(func_name, arguments))

    if not tool_calls:
        return text, []

    cleaned = STRICT_TOOL_CALL.sub("", text).rstrip()
    return cleaned, tool_calls


def _extract_fuzzy(text: str) -> tuple[str, list[dict]]:
    """
    Tier 2: tolerant parser for malformed tool-call XML.

    Handles merged tags, missing angle brackets, wrapper params, unclosed blocks.
    """
    tool_calls: list[dict] = []

    # Try closed blocks first, then fall back to unclosed (to end-of-string)
    full_matches = list(FUZZY_BLOCK_FULL.finditer(text))
    inner_matches = list(FUZZY_BLOCK_INNER.finditer(text))

    if not full_matches:
        full_matches = list(FUZZY_BLOCK_FULL_EOT.finditer(text))
        inner_matches = list(FUZZY_BLOCK_INNER_EOT.finditer(text))

    for inner_m in inner_matches:
        block = inner_m.group(1)

        # Find function name – strategy 1: attribute-style  function=name
        func_m = FUZZY_FUNC_NAME_ATTR.search(block)
        func_name = func_m.group(1) if func_m else None

        # Strategy 2: bare tag <name> before first <parameter=
        if not func_name:
            param_pos = block.find("<parameter=")
            search_region = block[:param_pos] if param_pos != -1 else block[:200]
            for bare_m in FUZZY_FUNC_NAME_BARE.finditer(search_region):
                candidate = bare_m.group(1)
                if candidate.lower() not in _BARE_TAG_SKIP:
                    func_name = candidate
                    break

        if not func_name:
            logger.warning("Fuzzy: found tool_call block but no function name, skipping")
            continue

        # Extract leaf parameters (skips wrapper nesting)
        arguments = _extract_leaf_params(block)

        tool_calls.append(_make_tool_call_obj(func_name, arguments))
        logger.info(
            "Fuzzy-parsed tool call: function=%s, %d param(s)",
            func_name,
            len(arguments),
        )

    if not tool_calls:
        return text, []

    # Remove matched blocks from text
    cleaned = text
    for fm in reversed(full_matches):  # reverse to preserve indices
        cleaned = cleaned[: fm.start()] + cleaned[fm.end() :]
    cleaned = cleaned.rstrip()
    return cleaned, tool_calls


def extract_tool_calls_from_text(text: str) -> tuple[str, list[dict]]:
    """
    Scan *text* for <tool_call>…</tool_call> blocks (well-formed or malformed).

    Uses strict regex first, falls back to fuzzy parser if strict finds nothing
    but tool-call markers are present.

    Returns
    -------
    cleaned : str
        The input with all tool-call blocks removed and trailing whitespace stripped.
    tool_calls : list[dict]
        OpenAI-compatible tool_call objects extracted from the blocks.
    """
    if not text:
        return text, []

    # Quick bail-out: no hint of tool calls at all
    if not HAS_TOOL_CALL_HINT.search(text):
        # Check for orphaned <parameter= tags — not recoverable as a tool call
        # but worth logging so the operator knows the model is misbehaving
        if HAS_ORPHAN_PARAM_HINT.search(text):
            logger.warning(
                "Detected orphaned <parameter= tags in reasoning without any "
                "tool_call/tools/function wrapper — cannot recover a tool call"
            )
            if EMIT_NOOP_ON_ORPHAN:
                logger.info("Emitting synthetic noop tool call to keep agent loop alive")
                return text, [_make_noop_tool_call()]
        return text, []

    # Tier 1: strict
    cleaned, calls = _extract_strict(text)
    if calls:
        logger.debug("Strict parser extracted %d tool call(s)", len(calls))
        return cleaned, calls

    # Tier 2: fuzzy
    logger.debug("Strict parser found nothing, trying fuzzy parser")
    cleaned, calls = _extract_fuzzy(text)
    if calls:
        logger.info("Fuzzy parser recovered %d tool call(s)", len(calls))
    return cleaned, calls
