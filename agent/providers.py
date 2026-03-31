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
    Some models output tool calls as raw text instead of the structured
    tool_calls field.  Handles the following formats (in priority order):

      <tool_call>{"name": "foo", ...}</tool_call>       — Gemma native template
      <function=foo({"arg": 1})</function>               — Llama HF failed_generation
      foo({"arg": 1})                                    — Python-call style (Qwen)
      {"name": "foo", "arguments"|"parameters": {...}}  — plain JSON
      foo,                                               — bare tool name (Gemma fallback)

    Only accepted when `name` matches a known tool.
    """
    text = text.strip()
    known = {t["function"]["name"] for t in tools} if tools else set()

    # ── Gemma <tool_call>...</tool_call> XML wrapper ───────────────────────────
    xml_match = re.search(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL)
    if xml_match:
        inner = xml_match.group(1).strip()
        try:
            obj = json.loads(inner)
            if isinstance(obj, dict):
                name = obj.get("name")
                if name and (not known or name in known):
                    args = obj.get("arguments") or obj.get("parameters") or {}
                    return ToolCall(name=name, arguments=args if isinstance(args, dict) else {}, id="text-fallback")
        except (json.JSONDecodeError, ValueError):
            pass

    # ── Llama/HF <function=name(json_args)</function> ─────────────────────────
    fn_match = re.search(r"<function=(\w+)\s*\((\{.*?\})\s*\)\s*</function>", text, re.DOTALL)
    if fn_match:
        name, raw_args = fn_match.group(1), fn_match.group(2)
        if not known or name in known:
            try:
                args = json.loads(raw_args)
            except (json.JSONDecodeError, ValueError):
                args = {}
            return ToolCall(name=name, arguments=args if isinstance(args, dict) else {}, id="text-fallback")

    # ── Python-call style: name({"arg": val}) — seen in Qwen prose output ─────
    py_match = re.match(r"^(\w+)\s*\((\{.*\})\)\s*$", text, re.DOTALL)
    if py_match:
        name, raw_args = py_match.group(1), py_match.group(2)
        if not known or name in known:
            try:
                args = json.loads(raw_args)
                return ToolCall(name=name, arguments=args if isinstance(args, dict) else {}, id="text-fallback")
            except (json.JSONDecodeError, ValueError):
                pass

    # ── Strip optional markdown code fences ───────────────────────────────────
    clean = re.sub(r"^```(?:json)?\s*", "", text)
    clean = re.sub(r"\s*```$", "", clean).strip()

    # ── Standard JSON object {"name": ..., "arguments"|"parameters": ...} ─────
    try:
        obj = json.loads(clean)
        if isinstance(obj, dict):
            name = obj.get("name")
            if name and isinstance(name, str) and (not known or name in known):
                args = obj.get("parameters") or obj.get("arguments") or {}
                return ToolCall(name=name, arguments=args if isinstance(args, dict) else {}, id="text-fallback")
    except (json.JSONDecodeError, ValueError):
        pass

    # ── Bare tool name — Gemma sometimes emits just the name (with optional
    #    trailing comma/parens) when it can't format a proper tool call ─────────
    bare = clean.rstrip(",()\n\r ").strip()
    if bare and known and bare in known:
        return ToolCall(name=bare, arguments={}, id="text-fallback")

    return None


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

    # Convert messages to a strictly alternating user/assistant sequence.
    #
    # HF models (especially Gemma) reject role="tool" messages with a 400
    # "Conversation roles must alternate" error.  Instead we:
    #   • Replace assistant messages that contain tool_calls with a plain
    #     assistant text message (no tool_calls key).
    #   • Collect every tool-result payload into a list.
    #   • Append a single injected user message at the end that embeds all the
    #     tool results so the model can summarise them without calling tools again.
    hf_messages = []
    has_tool_results = False
    collected_tool_results: list[str] = []

    for msg in messages:
        if msg["role"] == "tool":
            # Collect result; will be embedded in the injected user message below
            collected_tool_results.append(str(msg["content"]))
            has_tool_results = True
        elif msg["role"] == "assistant" and msg.get("tool_calls"):
            # Emit a plain assistant turn — no tool_calls key so the conversation
            # stays strictly alternating for models that require it.
            hf_messages.append({
                "role": "assistant",
                "content": msg.get("content") or "I'll look that up for you.",
            })
        else:
            hf_messages.append({"role": msg["role"], "content": msg["content"]})

    # Once tool results exist, append a user message that carries the results
    # and asks the model to summarise.  Omitting tools from the payload (below)
    # forces a text-only answer.
    if has_tool_results:
        results_block = "\n\n".join(
            f"Tool result {i + 1}:\n{r}" for i, r in enumerate(collected_tool_results)
        )
        hf_messages.append({
            "role": "user",
            "content": (
                f"{results_block}\n\n"
                "Using the tool results above, answer the original question clearly and concisely."
            ),
        })

    payload: dict = {
        "model": model_id,
        "messages": hf_messages,
        "temperature": temperature,
        "max_tokens": 4096,
    }
    # Only include the tools schema when we still need the model to pick a tool.
    # Once tool results are in context we omit tools entirely so Gemma (and other
    # weaker HF models) cannot attempt another tool call and are forced to produce
    # a plain-text answer.
    if tools and not has_tool_results:
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
        # HF returns 400 with code "tool_use_failed" when the model generates a
        # tool call in a non-standard format (e.g. Llama: <function=name(args)></function>).
        # Try to recover by parsing the failed_generation field before giving up.
        if r.status_code == 400 and tools:
            try:
                err = r.json().get("error", {})
                failed_gen = err.get("failed_generation", "")
                if failed_gen:
                    tc = _try_parse_text_tool_call(failed_gen, tools)
                    if tc:
                        return ChatResult(text="", tool_calls=[tc])
            except Exception:
                pass
        raise RuntimeError(f"HuggingFace API error {r.status_code}: {r.text[:300]}")

    data = r.json()
    choice = data["choices"][0]["message"]

    raw_tool_calls = choice.get("tool_calls") or []
    if raw_tool_calls:
        tcs = []
        for tc in raw_tool_calls:
            fn = tc.get("function", {})
            args = fn.get("arguments") or "{}"  # HF can return null; default to empty
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            elif not isinstance(args, dict):
                args = {}
            tcs.append(ToolCall(name=fn["name"], arguments=args, id=tc.get("id", "")))
        return ChatResult(text=choice.get("content") or "", tool_calls=tcs)

    hf_content = choice.get("content") or ""
    if hf_content and tools:
        tc = _try_parse_text_tool_call(hf_content, tools)
        if tc:
            return ChatResult(text="", tool_calls=[tc])
    return ChatResult(text=hf_content)
