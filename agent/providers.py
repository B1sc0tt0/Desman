"""
Multi-provider LLM client.

Supports:
  - Ollama       (local, via ollama SDK)           — always available
  - Anthropic    (Claude, via anthropic SDK)        — pip install anthropic
  - OpenAI       (GPT-4o etc., via openai SDK)     — pip install openai
  - HuggingFace  (Inference API, via httpx)        — no extra install needed

Model string format:
  Ollama:       "llama3.1:8b"                          (no prefix)
  Anthropic:    "anthropic:claude-sonnet-4-6"
  OpenAI:       "openai:gpt-4o"
  HuggingFace:  "huggingface:Qwen/Qwen2.5-72B-Instruct"
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    name: str
    arguments: dict
    id: str = ""


@dataclass
class ChatResult:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


def parse_model_string(model_string: str) -> tuple[str, str]:
    """Returns (provider, model_id). Default provider is 'ollama'."""
    if ":" in model_string:
        prefix, rest = model_string.split(":", 1)
        if prefix in ("anthropic", "openai", "huggingface"):
            return prefix, rest
    return "ollama", model_string


def chat(
    model_string: str,
    messages: list[dict],
    tools: list[dict],
    temperature: float,
    cfg: dict,
    external_apis: dict,
) -> ChatResult:
    """Route chat to the appropriate provider and return a ChatResult."""
    provider, model_id = parse_model_string(model_string)

    if provider == "anthropic":
        api_key = external_apis.get("anthropic", {}).get("api_key", "")
        return _chat_anthropic(model_id, messages, tools, temperature, api_key)
    elif provider == "openai":
        api_key = external_apis.get("openai", {}).get("api_key", "")
        return _chat_openai(model_id, messages, tools, temperature, api_key)
    elif provider == "huggingface":
        api_key = external_apis.get("huggingface", {}).get("api_key", "")
        return _chat_huggingface(model_id, messages, tools, temperature, api_key)
    else:
        base_url = cfg.get("ollama", {}).get("base_url", "http://localhost:11434")
        return _chat_ollama(model_id, messages, tools, temperature, base_url)


# ── Text-based tool call fallback ─────────────────────────────────────────────

def _try_parse_text_tool_call(text: str, tools: list) -> ToolCall | None:
    """
    Some weaker models (Llama 3.2 3B, Gemma) output tool calls as raw JSON text
    instead of the structured tool_calls field.  Supports two common formats:
      {"name": "foo", "parameters": {...}}
      {"name": "foo", "arguments": {...}}
    Only accepted when `name` matches a known tool.
    """
    text = text.strip()
    # Strip optional markdown code fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    name = obj.get("name")
    if not name or not isinstance(name, str):
        return None
    args = obj.get("parameters") or obj.get("arguments") or {}
    if not isinstance(args, dict):
        return None
    if tools:
        known = {t["function"]["name"] for t in tools}
        if name not in known:
            return None
    return ToolCall(name=name, arguments=args, id="text-fallback")


# ── Ollama ────────────────────────────────────────────────────────────────────

def _chat_ollama(model_id, messages, tools, temperature, base_url) -> ChatResult:
    import ollama as ollama_sdk
    client = ollama_sdk.Client(host=base_url)
    response = client.chat(
        model=model_id,
        messages=messages,
        tools=tools if tools else None,
        stream=False,
        options={"temperature": temperature},
    )
    msg = response.message
    if msg.tool_calls:
        tcs = []
        for tc in msg.tool_calls:
            args = tc.function.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tcs.append(ToolCall(name=tc.function.name, arguments=args))
        return ChatResult(text=msg.content or "", tool_calls=tcs)
    # Fallback: model emitted a JSON tool call in the text instead of tool_calls
    content = msg.content or ""
    if content and tools:
        tc = _try_parse_text_tool_call(content, tools)
        if tc:
            return ChatResult(text="", tool_calls=[tc])
    return ChatResult(text=content)


# ── Anthropic ─────────────────────────────────────────────────────────────────

def _chat_anthropic(model_id, messages, tools, temperature, api_key) -> ChatResult:
    try:
        import anthropic
    except ImportError:
        raise ImportError(
            "Anthropic package not installed. Run: uv pip install anthropic"
        )

    client = anthropic.Anthropic(api_key=api_key)

    anthropic_tools = [
        {
            "name": t["function"]["name"],
            "description": t["function"].get("description", ""),
            "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}}),
        }
        for t in (tools or [])
    ]

    system_prompt, converted = _to_anthropic_messages(messages)

    kwargs: dict = dict(
        model=model_id,
        max_tokens=4096,
        messages=converted,
        temperature=temperature,
    )
    if system_prompt:
        kwargs["system"] = system_prompt
    if anthropic_tools:
        kwargs["tools"] = anthropic_tools

    response = client.messages.create(**kwargs)

    tool_calls: list[ToolCall] = []
    text_parts: list[str] = []
    for block in response.content:
        if block.type == "tool_use":
            tool_calls.append(ToolCall(name=block.name, arguments=block.input, id=block.id))
        elif block.type == "text":
            text_parts.append(block.text)

    return ChatResult(text="".join(text_parts), tool_calls=tool_calls)


def _to_anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """Convert normalized message history to Anthropic format.
    Returns (system_prompt, messages_list).
    """
    system = ""
    converted: list[dict] = []

    for msg in messages:
        role = msg["role"]

        if role == "system":
            system = msg["content"]
            continue

        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id", ""),
                "content": str(msg["content"]),
            }
            # Merge consecutive tool results into one user message (Anthropic requires
            # alternating user/assistant turns)
            if (converted
                    and converted[-1]["role"] == "user"
                    and isinstance(converted[-1]["content"], list)):
                converted[-1]["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
            continue

        if role == "assistant" and msg.get("tool_calls"):
            content: list[dict] = []
            if msg.get("content"):
                content.append({"type": "text", "text": msg["content"]})
            for tc in msg["tool_calls"]:
                args = tc["function"]["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                content.append({
                    "type": "tool_use",
                    "id": tc.get("id") or f"toolu_{tc['function']['name']}",
                    "name": tc["function"]["name"],
                    "input": args,
                })
            converted.append({"role": "assistant", "content": content})
            continue

        converted.append({"role": role, "content": msg["content"]})

    return system, converted


# ── OpenAI ────────────────────────────────────────────────────────────────────

def _chat_openai(model_id, messages, tools, temperature, api_key) -> ChatResult:
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError(
            "OpenAI package not installed. Run: uv pip install openai"
        )

    client = OpenAI(api_key=api_key)

    openai_messages = []
    for msg in messages:
        if msg["role"] == "tool":
            openai_messages.append({
                "role": "tool",
                "tool_call_id": msg.get("tool_call_id", ""),
                "content": msg["content"],
            })
        elif msg["role"] == "assistant" and msg.get("tool_calls"):
            tc_list = []
            for tc in msg["tool_calls"]:
                args = tc["function"]["arguments"]
                if isinstance(args, dict):
                    args = json.dumps(args)
                tc_list.append({
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {"name": tc["function"]["name"], "arguments": args},
                })
            openai_messages.append({
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": tc_list,
            })
        else:
            openai_messages.append({"role": msg["role"], "content": msg["content"]})

    kwargs: dict = dict(
        model=model_id,
        messages=openai_messages,
        temperature=temperature,
    )
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    response = client.chat.completions.create(**kwargs)
    choice = response.choices[0].message

    if choice.tool_calls:
        tcs = []
        for tc in choice.tool_calls:
            args = tc.function.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tcs.append(ToolCall(name=tc.function.name, arguments=args, id=tc.id))
        return ChatResult(text=choice.content or "", tool_calls=tcs)

    return ChatResult(text=choice.content or "")


# ── HuggingFace ───────────────────────────────────────────────────────────────

_HF_BASE_URL = "https://router.huggingface.co/v1"


def _chat_huggingface(model_id, messages, tools, temperature, api_key) -> ChatResult:
    """
    Calls the HuggingFace Serverless Inference API using its OpenAI-compatible
    /v1/chat/completions endpoint. Uses httpx (already a project dependency).

    Not all HF models support tool calling — if the model returns plain text
    when tools are provided, the response is treated as a normal text reply.
    """
    import httpx

    # Convert messages to OpenAI format (same as _chat_openai)
    hf_messages = []
    for msg in messages:
        if msg["role"] == "tool":
            hf_messages.append({
                "role": "tool",
                "tool_call_id": msg.get("tool_call_id", ""),
                "content": msg["content"],
            })
        elif msg["role"] == "assistant" and msg.get("tool_calls"):
            tc_list = []
            for tc in msg["tool_calls"]:
                args = tc["function"]["arguments"]
                if isinstance(args, dict):
                    args = json.dumps(args)
                tc_list.append({
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {"name": tc["function"]["name"], "arguments": args},
                })
            hf_messages.append({
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": tc_list,
            })
        else:
            hf_messages.append({"role": msg["role"], "content": msg["content"]})

    payload: dict = {
        "model": model_id,
        "messages": hf_messages,
        "temperature": temperature,
        "max_tokens": 4096,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    with httpx.Client(timeout=60.0) as client:
        r = client.post(
            f"{_HF_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if r.status_code != 200:
        raise RuntimeError(f"HuggingFace API error {r.status_code}: {r.text[:300]}")

    data = r.json()
    choice = data["choices"][0]["message"]

    raw_tool_calls = choice.get("tool_calls") or []
    if raw_tool_calls:
        tcs = []
        for tc in raw_tool_calls:
            fn = tc.get("function", {})
            args = fn.get("arguments", "{}")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tcs.append(ToolCall(name=fn["name"], arguments=args, id=tc.get("id", "")))
        return ChatResult(text=choice.get("content") or "", tool_calls=tcs)

    hf_content = choice.get("content") or ""
    if hf_content and tools:
        tc = _try_parse_text_tool_call(hf_content, tools)
        if tc:
            return ChatResult(text="", tool_calls=[tc])
    return ChatResult(text=hf_content)
