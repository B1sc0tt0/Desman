"""
Tool scoping utility — filters the full MCP tool list down to only the tools
a specific worker agent is allowed to see.

This is the mechanism that enforces worker specialisation: a Freshdesk worker
only receives freshdesk_* tools, a Freshservice worker only freshservice_* tools,
and so on. Workers cannot accidentally call tools outside their domain.

Pattern format (matches tool function names):
  "freshdesk_*"    → all tools prefixed with freshdesk_
  "freshservice_*" → all tools prefixed with freshservice_
  "rag_*"          → all RAG tools
  "*"              → all tools (unrestricted — use with care)
  []               → no tools (text-only / retrieval-only worker)
"""
from __future__ import annotations

import fnmatch


def filter_tools_by_pattern(tools: list[dict], pattern: str | list) -> list[dict]:
    """
    Return only the tools whose function name matches the given pattern.

    Args:
        tools:   Full list of MCP tool dicts in OpenAI-compatible format,
                 as returned by SessionManager.all_tools().
        pattern: Glob string (e.g. "freshdesk_*"), empty list [] for no tools,
                 or "*" for all tools. Matches against the tool's function name.

    Returns:
        Filtered list of tool dicts. Order is preserved.
    """
    if isinstance(pattern, list):
        # Explicit empty list in config → worker has no tool access (text-only)
        return []

    if not pattern or pattern == "*":
        # Unrestricted or catch-all pattern
        return list(tools)

    return [
        t for t in tools
        if fnmatch.fnmatch(t["function"]["name"], pattern)
    ]
