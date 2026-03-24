#!/usr/bin/env python3
"""
Pre-flight checks. Run before starting the agent.
Usage: python scripts/check_env.py
"""
import sys
import platform
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def check(label: str, ok: bool, detail: str = "") -> None:
    status = "✓" if ok else "✗"
    line = f"  {status} {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    if not ok:
        sys.exit(1)


print("\nDesman — environment check\n")

# Python version
major, minor, *_ = platform.python_version_tuple()
check("Python >=3.12", int(major) >= 3 and int(minor) >= 12, platform.python_version())

# Config exists and is valid
from agent.config import load_config, ConfigError, get_mcp_server_configs

config_path = Path(__file__).parent.parent / "config" / "config.local.yaml"
check("config.local.yaml exists", config_path.exists(), str(config_path))

try:
    cfg = load_config()
    check("Config parses and validates", True)
except ConfigError as e:
    check("Config parses and validates", False, str(e))

# Ollama reachable
import httpx

try:
    r = httpx.get(f"{cfg['ollama']['base_url']}/api/tags", timeout=3)
    check("Ollama reachable", r.status_code == 200, cfg["ollama"]["base_url"])
    models = [m["name"] for m in r.json().get("models", [])]
    check("At least one model available", len(models) > 0, ", ".join(models[:3]) or "none")
except Exception as e:
    check("Ollama reachable", False, str(e))

# MCP server scripts present
for srv in get_mcp_server_configs(cfg):
    script = Path(srv["args"][0])
    check(f"MCP '{srv['name']}' script found", script.exists(), str(script))
    env_file = srv.get("env_file")
    if env_file:
        check(f"MCP '{srv['name']}' .env found", Path(env_file).exists(), env_file)
    else:
        print(f"  ! MCP '{srv['name']}' — no .env file found (credentials missing)")

print("\nAll checks passed.\n")
