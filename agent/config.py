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
MCP_SERVERS_DIR = ROOT / "mcp_servers"


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
        for field in ("display_name", "ollama_model"):
            if field not in m:
                raise ConfigError(f"models[{i}] is missing required field '{field}'")


def get_system_prompt(cfg: dict) -> str:
    """Returns the admin-defined system prompt. Never exposed to the UI layer."""
    return cfg["agent"]["system_prompt"].strip()


def get_curated_models(cfg: dict) -> list[dict]:
    return cfg["models"]


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
