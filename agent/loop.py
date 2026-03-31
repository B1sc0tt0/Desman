"""
Agent loop: receives user input, runs tool call iterations via MCP, streams final response.

Flow per user message:
  1. Build message list (system prompt + history + new user message)
  2. Call the selected provider (Ollama / Anthropic / OpenAI) with tools list
  3. If provider returns tool_calls: dispatch via MCPSessionManager, append results, go to 2
  4. If provider returns plain text: stream it to the UI
  5. Enforce max_iterations to prevent runaway loops

Provider routing is based on the model_string prefix:
  "llama3.1:8b"                → Ollama (local)
  "anthropic:claude-sonnet-4-6" → Anthropic API
  "openai:gpt-4o"              → OpenAI API
"""
from __future__ import annotations

import re
from typing import Generator

from .config import get_system_prompt
from .mcp_client import SessionManager
from .providers import chat as provider_chat


def run(
    user_message: str,
    history: list[dict],
    model: str,
    cfg: dict,
    session_manager: SessionManager,
    disabled_servers: list[str] | None = None,
    external_apis: dict | None = None,
) -> Generator[str, None, None]:
    """
    Yields response tokens (strings).

    model:         model_string including provider prefix for external models.
    history:       list of {"role": ..., "content": ...} — excludes current message.
    external_apis: loaded external_apis.yaml dict, or empty dict for Ollama-only.
    """
    system_prompt = get_system_prompt(cfg)
    max_iterations = cfg["agent"].get("max_iterations", 10)
    temperature = cfg["agent"].get("temperature", 0.3)
    ext = external_apis or {}

    tools = session_manager.all_tools()
    if disabled_servers:
        tools = [
            t for t in tools
            if not any(t["function"]["name"].startswith(f"{s}_") for s in disabled_servers)
        ]

    messages = [{"role": "system", "content": system_prompt}]
    messages += history
    messages.append({"role": "user", "content": user_message})

    for iteration in range(max_iterations):
        result = provider_chat(model, messages, tools, temperature, cfg, ext)

        # ── Tool call branch ──────────────────────────────────────────────────
        if result.has_tool_calls:
            messages.append({
                "role": "assistant",
                "content": "",  # Drop any text the model emitted alongside tool_calls — some models (Gemma via HF) output partial tool-call text as content, which gets echoed back on the next turn
                "tool_calls": [
                    {
                        "id": tc.id,
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in result.tool_calls
                ],
            })

            for tc in result.tool_calls:
                yield f"*[Calling tool: {tc.name}...]*\n"
                tool_result = session_manager.call_tool(tc.name, tc.arguments)
                yield f"*[Tool result: {tool_result}]*\n"

                messages.append({
                    "role": "tool",
                    "content": tool_result,
                    "tool_call_id": tc.id,
                })

            continue

        # ── Text response branch ──────────────────────────────────────────────
        # Strip <think>...</think> blocks produced by reasoning models (e.g. qwen3)
        final_text = re.sub(
            r"<think>.*?</think>", "", result.text or "", flags=re.DOTALL
        ).strip()

        if not final_text:
            yield "(No response)"
            return

        chunk_size = 8
        for i in range(0, len(final_text), chunk_size):
            yield final_text[i:i + chunk_size]
        return

    yield (
        f"\n\n*[Agent reached the maximum of {max_iterations} iterations "
        f"without completing. Try rephrasing your request.]*"
    )
