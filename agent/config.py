"""
Loads and validates the admin YAML config.
All paths are resolved relative to the Desman root directory,
so the project is fully self-contained and portable across machines.

MCP servers run inside Desman's own venv — no per-server venv required.
All dependencies are declared in the root pyproject.toml.
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any

import yaml

# Desman root = two levels up from this file (agent/config.py -> agent/ -> root)
ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "config.local.yaml"
EXTERNAL_APIS_PATH = ROOT / "config" / "external_apis.yaml"
MCP_SERVERS_DIR = ROOT / "mcp_servers"

_DEFAULT_ANTHROPIC_MODELS = [
    {"display_name": "Claude Sonnet 4.6", "model_id": "claude-sonnet-4-6"},
    {"display_name": "Claude Haiku 4.5", "model_id": "claude-haiku-4-5-20251001"},
    {"display_name": "Claude Opus 4.6",  "model_id": "claude-opus-4-6"},
]

_DEFAULT_OPENAI_MODELS = [
    {"display_name": "GPT-4o",       "model_id": "gpt-4o"},
    {"display_name": "GPT-4o Mini",  "model_id": "gpt-4o-mini"},
    {"display_name": "GPT-4 Turbo",  "model_id": "gpt-4-turbo"},
]

_DEFAULT_HF_IMAGE_MODELS = [
    {"display_name": "Image — FLUX.1 Dev",     "hf_model": "black-forest-labs/FLUX.1-dev",     "type": "image"},
    {"display_name": "Image — FLUX.1 Schnell", "hf_model": "black-forest-labs/FLUX.1-schnell", "type": "image"},
]

# Models known to support tool calling on HF Serverless Inference API (free tier)
_DEFAULT_HF_MODELS = [
    {"display_name": "Llama 3.3 70B (HF)",   "model_id": "meta-llama/Llama-3.3-70B-Instruct"},
    {"display_name": "Llama 3.1 8B (HF)",    "model_id": "meta-llama/Llama-3.1-8B-Instruct"},
    {"display_name": "Qwen 2.5 72B (HF)",    "model_id": "Qwen/Qwen2.5-72B-Instruct"},
    {"display_name": "Qwen 2.5 7B (HF)",     "model_id": "Qwen/Qwen2.5-7B-Instruct"},
    {"display_name": "Mistral 7B v0.3 (HF)", "model_id": "mistralai/Mistral-7B-Instruct-v0.3"},
    {"display_name": "Mixtral 8x7B (HF)",    "model_id": "mistralai/Mixtral-8x7B-Instruct-v0.1"},
    {"display_name": "Gemma 3 27B (HF)",     "model_id": "google/gemma-3-27b-it"},
    {"display_name": "MiniMax M2.5 (HF)",    "model_id": "MiniMaxAI/MiniMax-M2.5"},
]


class ConfigError(Exception):
    pass


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(
            f"Config not found at {path}.\n"
            f"Copy config/config.example.yaml to config/config.local.yaml and fill in your values."
        )
    with open(path) as f:
        cfg = yaml.safe_load(f)
    _validate(cfg)
    return cfg


def _validate(cfg: dict) -> None:
    required = ["agent", "ollama", "mcp_servers", "models"]
    for key in required:
        if key not in cfg:
            raise ConfigError(f"Missing required config section: '{key}'")
    if "system_prompt" not in cfg["agent"]:
        raise ConfigError("agent.system_prompt is required")
    if not cfg["mcp_servers"]:
        raise ConfigError("At least one MCP server must be defined under mcp_servers")
    for i, srv in enumerate(cfg["mcp_servers"]):
        for field in ("name", "folder", "script"):
            if field not in srv:
                raise ConfigError(f"mcp_servers[{i}] is missing required field '{field}'")
    if not cfg["models"]:
        raise ConfigError("At least one model must be defined under models")
    for i, m in enumerate(cfg["models"]):
        if "display_name" not in m:
            raise ConfigError(f"models[{i}] is missing required field 'display_name'")
        if m.get("type") == "image":
            if "hf_model" not in m:
                raise ConfigError(f"models[{i}] (type: image) is missing required field 'hf_model'")
        else:
            if "ollama_model" not in m:
                raise ConfigError(f"models[{i}] is missing required field 'ollama_model'")


def get_system_prompt(cfg: dict) -> str:
    """Returns the admin-defined system prompt. Never exposed to the UI layer."""
    return cfg["agent"]["system_prompt"].strip()


def get_curated_models(cfg: dict) -> list[dict]:
    # Exclude image-type entries — they go through the HF image API, not Ollama
    return [m for m in cfg["models"] if m.get("type") != "image"]


def load_external_apis() -> dict:
    """Load external API config. Returns empty dict if file doesn't exist."""
    if not EXTERNAL_APIS_PATH.exists():
        return {}
    with open(EXTERNAL_APIS_PATH) as f:
        return yaml.safe_load(f) or {}


def save_external_apis(data: dict) -> None:
    """Write external API config to disk."""
    EXTERNAL_APIS_PATH.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))


def get_external_models(external_apis: dict) -> list[dict]:
    """
    Returns list of enabled external models.
    Each entry: {display_name, model_string (with provider prefix), provider, type}
    Only included when the provider is enabled AND has a non-empty api_key.

    Image models use the synthetic prefix "hfimage:" so callers can detect them
    without inspecting the type field separately.
    """
    models = []
    anthropic = external_apis.get("anthropic", {})
    if anthropic.get("enabled") and anthropic.get("api_key"):
        for m in anthropic.get("models", _DEFAULT_ANTHROPIC_MODELS):
            models.append({
                "display_name": m["display_name"],
                "model_string": f"anthropic:{m['model_id']}",
                "provider": "anthropic",
                "type": "text",
            })

    openai = external_apis.get("openai", {})
    if openai.get("enabled") and openai.get("api_key"):
        for m in openai.get("models", _DEFAULT_OPENAI_MODELS):
            models.append({
                "display_name": m["display_name"],
                "model_string": f"openai:{m['model_id']}",
                "provider": "openai",
                "type": "text",
            })

    huggingface = external_apis.get("huggingface", {})
    if huggingface.get("enabled") and huggingface.get("api_key"):
        for m in huggingface.get("models", _DEFAULT_HF_MODELS):
            models.append({
                "display_name": m["display_name"],
                "model_string": f"huggingface:{m['model_id']}",
                "provider": "huggingface",
                "type": "text",
            })
        for m in huggingface.get("image_models", _DEFAULT_HF_IMAGE_MODELS):
            models.append({
                "display_name": m["display_name"],
                "model_string": f"hfimage:{m['hf_model']}",
                "provider": "huggingface",
                "type": "image",
            })

    return models


def get_mcp_server_configs(cfg: dict) -> list[dict]:
    """
    Returns enabled MCP server configs with all paths resolved to absolute.

    MCP server scripts run using the same Python interpreter as Desman itself
    (sys.executable), so no per-server venv is needed. All dependencies are
    managed in the root pyproject.toml.

    Each returned entry has:
        name        str        — server identifier
        command     str        — path to Python interpreter (Desman's own)
        args        list[str]  — [absolute path to server script]
        env_file    str|None   — absolute path to the server's .env, or None
        enabled     bool
    """
    result = []
    for srv in cfg["mcp_servers"]:
        if not srv.get("enabled", True):
            continue

        folder = MCP_SERVERS_DIR / srv["folder"]
        script = folder / srv["script"]
        env_file = folder / ".env"

        if not folder.exists():
            print(f"[CONFIG] WARNING: MCP server folder not found: {folder} — skipping '{srv['name']}'")
            continue
        if not script.exists():
            print(f"[CONFIG] WARNING: MCP server script not found: {script} — skipping '{srv['name']}'")
            continue

        result.append({
            "name": srv["name"],
            "command": sys.executable,   # Desman's own venv Python
            "args": [str(script)],
            "env_file": str(env_file) if env_file.exists() else None,
            "enabled": True,
        })

    return result
