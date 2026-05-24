"""Generate / install MCP-style config for AI coding assistants.

Currently supported targets:

- ``claude``  — Claude Desktop / Claude Code MCP servers config
- ``cursor``  — Cursor IDE ``.cursor/mcp.json``
- ``codex``   — OpenAI Codex CLI ``~/.codex/mcp_config.json``

The default behavior is conservative: print a snippet the user can paste. Use
``write=True`` (CLI ``--yes``) to merge into the assistant's config file.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SUPPORTED_ASSISTANTS = ("claude", "cursor", "codex")

DEFAULT_SERVER_NAME = "codegraphkb"


@dataclass
class InstallResult:
    assistant: str
    config: dict
    config_path: Path | None
    written: bool
    action: str  # "printed", "written", "would_write"
    notes: list[str]


def build_mcp_server_entry(repo: Path, *, server_name: str = DEFAULT_SERVER_NAME) -> dict:
    return {
        server_name: {
            "command": "codegraph",
            "args": ["serve", "mcp", "--repo", str(repo.resolve())],
        }
    }


def build_assistant_config(assistant: str, repo: Path) -> dict:
    """Return the config blob the assistant expects.

    Keep them aligned (all use the ``mcpServers`` key) — assistants currently differ
    only in *where* they read this file, not its shape.
    """
    if assistant not in SUPPORTED_ASSISTANTS:
        raise ValueError(
            f"Unsupported assistant {assistant!r}. Expected one of: {', '.join(SUPPORTED_ASSISTANTS)}"
        )
    return {"mcpServers": build_mcp_server_entry(repo)}


def default_config_path(assistant: str, repo: Path) -> Path | None:
    """Best-effort default file location for each assistant on the current OS.

    Returns ``None`` if no canonical location is known on this platform.
    """
    home = Path.home()
    if assistant == "claude":
        if sys.platform.startswith("darwin"):
            return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        if sys.platform.startswith("win"):
            appdata = os.environ.get("APPDATA")
            if appdata:
                return Path(appdata) / "Claude" / "claude_desktop_config.json"
            return None
        return home / ".config" / "Claude" / "claude_desktop_config.json"
    if assistant == "cursor":
        return repo.resolve() / ".cursor" / "mcp.json"
    if assistant == "codex":
        return home / ".codex" / "mcp_config.json"
    return None


def install_assistant(
    assistant: str,
    repo: Path,
    *,
    write: bool = False,
    config_path: Path | None = None,
    print_only: bool = False,
    stream=None,
) -> InstallResult:
    """Install or print MCP config for ``assistant``.

    ``write=True`` merges the config into ``config_path`` (or the default for the
    platform). Without ``write`` we always print the JSON.
    """
    stream = stream or sys.stdout

    config = build_assistant_config(assistant, repo)
    resolved_path = config_path or default_config_path(assistant, repo)

    notes: list[str] = []
    if resolved_path is None:
        notes.append(
            f"No default config path is known for {assistant!r} on this platform; "
            "pass --config <path> or copy the snippet manually."
        )

    if print_only or not write:
        stream.write(json.dumps(config, indent=2) + os.linesep)
        if resolved_path is not None:
            notes.append(f"Suggested location: {resolved_path}")
        return InstallResult(
            assistant=assistant,
            config=config,
            config_path=resolved_path,
            written=False,
            action="printed",
            notes=notes,
        )

    if resolved_path is None:
        raise RuntimeError(
            f"Cannot write {assistant!r} config — no default path on this platform. "
            "Pass --config <path>."
        )

    merged = merge_into_existing(resolved_path, config)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    notes.append(f"Wrote {resolved_path}")
    return InstallResult(
        assistant=assistant,
        config=merged,
        config_path=resolved_path,
        written=True,
        action="written",
        notes=notes,
    )


def uninstall_assistant(
    assistant: str,
    *,
    config_path: Path | None = None,
    server_name: str = DEFAULT_SERVER_NAME,
    repo: Path | None = None,
) -> InstallResult:
    resolved_path = config_path or default_config_path(
        assistant, repo or Path.cwd()
    )
    if resolved_path is None or not resolved_path.exists():
        return InstallResult(
            assistant=assistant,
            config={},
            config_path=resolved_path,
            written=False,
            action="printed",
            notes=[f"Nothing to remove at {resolved_path}" if resolved_path else "No config path"],
        )
    try:
        data = json.loads(resolved_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return InstallResult(
            assistant=assistant,
            config={},
            config_path=resolved_path,
            written=False,
            action="printed",
            notes=[f"Could not parse {resolved_path}: {exc}"],
        )

    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or server_name not in servers:
        return InstallResult(
            assistant=assistant,
            config=data,
            config_path=resolved_path,
            written=False,
            action="printed",
            notes=[f"No {server_name!r} entry in {resolved_path}"],
        )

    servers.pop(server_name, None)
    if not servers:
        data.pop("mcpServers", None)
    resolved_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return InstallResult(
        assistant=assistant,
        config=data,
        config_path=resolved_path,
        written=True,
        action="written",
        notes=[f"Removed {server_name!r} from {resolved_path}"],
    )


def merge_into_existing(path: Path, new_config: dict) -> dict:
    """Merge ``new_config`` into the JSON file at ``path``.

    Behavior:
    - Missing or unreadable file -> use ``new_config`` verbatim.
    - Existing ``mcpServers`` dict -> add/replace our entries; leave others untouched.
    """
    if not path.exists():
        return new_config

    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return new_config

    if not isinstance(existing, dict):
        return new_config

    new_servers = new_config.get("mcpServers", {})
    existing_servers = existing.get("mcpServers")
    if isinstance(existing_servers, dict):
        existing_servers.update(new_servers)
    else:
        existing["mcpServers"] = dict(new_servers)
    return existing


def iter_supported() -> Iterable[str]:
    return iter(SUPPORTED_ASSISTANTS)
