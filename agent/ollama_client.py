"""
Thin wrapper around the Ollama Python SDK.
Handles model listing, availability filtering, and streaming completions.
"""
from __future__ import annotations
from typing import Generator

import ollama


def list_local_models(base_url: str = "http://localhost:11434") -> list[str]:
    """Returns sorted list of all model name strings available locally in Ollama."""
    client = ollama.Client(host=base_url)
    try:
        result = client.list()
        return sorted(m.model for m in result.models)
    except Exception as e:
        raise RuntimeError(
            f"Cannot reach Ollama at {base_url}. Is it running? (ollama serve)"
        ) from e


def filter_to_available(
    curated: list[dict],
    base_url: str = "http://localhost:11434",
) -> list[dict]:
    """
    Given the admin's curated model list from config, returns only entries
    whose ollama_model is actually pulled locally.

    Each entry is a dict with keys: display_name, ollama_model, description.
    Returns the filtered list in the same order as the curated list.

    Matching is exact first, then prefix-based to handle Ollama's full tag strings
    e.g. config "llama3.1:8b" matches local "llama3.1:8b-instruct-q4_K_M".
    """
    local = set(list_local_models(base_url))

    def is_available(ollama_model: str) -> bool:
        if ollama_model in local:
            return True
        prefix = ollama_model.split(":")[0] + ":"
        return any(m.startswith(prefix) for m in local)

    return [entry for entry in curated if is_available(entry["ollama_model"])]


def chat_stream(
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    base_url: str = "http://localhost:11434",
    temperature: float = 0.3,
) -> Generator[str, None, None]:
    """Streams chat response tokens. Yields text chunks."""
    client = ollama.Client(host=base_url)
    kwargs: dict = dict(
        model=model,
        messages=messages,
        stream=True,
        options={"temperature": temperature},
    )
    if tools:
        kwargs["tools"] = tools
    for chunk in client.chat(**kwargs):
        delta = chunk.message.content
        if delta:
            yield delta
