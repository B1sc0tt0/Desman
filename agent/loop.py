"""
Agent loop: receives user input, runs tool call iterations via MCP, streams final response.

Flow per user message:
  1. Build message list (system prompt + history + new user message)
  2. Call Ollama with tools list
  3. If Ollama returns a tool_call: dispatch via MCPSessionManager, append result, go to 2
  4. If Ollama returns plain text: stream it to the UI
  5. Enforce max_iterations to prevent runaway loops

Streaming note: Ollama does not stream when tool calls are in play (it needs the full
response to decide whether to invoke a tool). Only the final text response is streamed.
"""
from __future__ import annotations

import json
import re
from typing import Generator

import ollama as ollama_sdk

from .config import get_system_prompt
from .mcp_client import SessionManager


def run(
    user_message: str,
    history: list[dict],
    model: str,
    cfg: dict,
    session_manager: SessionManager,
    disabled_servers: list[str] | None = None,
) -> Generator[str, None, None]:
    """
    Yields response tokens (strings).

    history: list of {"role": "user"|"assistant"|"tool", "content": str}
             — does NOT include the current user_message yet.
    session_manager: live MCPSessionManager, created at app startup.
    disabled_servers: server names whose tools should be hidden from the model.
    """
    system_prompt = get_system_prompt(cfg)
    max_iterations = cfg["agent"].get("max_iterations", 10)
    temperature = cfg["agent"].get("temperature", 0.3)
    base_url = cfg["ollama"]["base_url"]
    tools = session_manager.all_tools()
    if disabled_servers:
        tools = [
            t for t in tools
            if not any(t["function"]["name"].startswith(f"{s}_") for s in disabled_servers)
        ]

    messages = [{"role": "system", "content": system_prompt}]
    messages += history
    messages.append({"role": "user", "content": user_message})

    client = ollama_sdk.Client(host=base_url)

    for iteration in range(max_iterations):
        # Non-streaming call when tools are available — Ollama requires the full
        # response to determine whether to invoke a tool.
        response = client.chat(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            stream=False,
            options={"temperature": temperature},
        )

        msg = response.message

        # ── Tool call branch ──────────────────────────────────────────────────
        if msg.tool_calls:
            # Append the assistant's tool call intent to the message history
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in msg.tool_calls
                ],
            })

            # Dispatch each tool call and append results
            for tc in msg.tool_calls:
                tool_name = tc.function.name
                # Ollama may return arguments as dict or JSON string depending on model
                arguments = tc.function.arguments
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                yield f"*[Calling tool: {tool_name}...]*\n"

                result = session_manager.call_tool(tool_name, arguments)
                yield f"*[Tool result: {result}]*\n"

                messages.append({
                    "role": "tool",
                    "content": result,
                })

            # Loop back — let Ollama process the tool result(s)
            continue

        # ── Text response branch ──────────────────────────────────────────────
        # No tool calls: stream the final text response token by token
        # Strip <think>...</think> blocks produced by reasoning models (e.g. qwen3)
        final_text = re.sub(r"<think>.*?</think>", "", msg.content or "", flags=re.DOTALL).strip()
        if not final_text:
            yield "(No response)"
            return

        # Stream in chunks — simulate streaming since we have the full string
        # Switch to actual streaming once Ollama stabilises stream+tools support
        chunk_size = 8
        for i in range(0, len(final_text), chunk_size):
            yield final_text[i:i + chunk_size]
        return

    # Hit max_iterations without a plain text response
    yield (
        f"\n\n*[Agent reached the maximum of {max_iterations} iterations "
        f"without completing. Try rephrasing your request.]*"
    )
