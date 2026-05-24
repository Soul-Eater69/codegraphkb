"""Tests for the AI assistant MCP installer commands (PR 6 / Phase 5)."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from codegraphkb.cli import cli
from codegraphkb.ux.installers import (
    SUPPORTED_ASSISTANTS,
    build_assistant_config,
    install_assistant,
    merge_into_existing,
    uninstall_assistant,
)


@pytest.mark.parametrize("assistant", SUPPORTED_ASSISTANTS)
def test_build_assistant_config_shape(assistant: str, tmp_path: Path) -> None:
    config = build_assistant_config(assistant, tmp_path)
    server = config["mcpServers"]["codegraphkb"]
    assert server["command"] == "codegraph"
    assert server["args"][0] == "serve"
    assert server["args"][1] == "mcp"
    assert "--repo" in server["args"]
    assert str(tmp_path.resolve()) in server["args"]


def test_build_assistant_config_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        build_assistant_config("unknown", Path("."))


def test_install_assistant_print_only_emits_valid_json(tmp_path: Path) -> None:
    stream = io.StringIO()
    result = install_assistant("claude", tmp_path, print_only=True, stream=stream)
    assert result.written is False
    assert result.action == "printed"
    parsed = json.loads(stream.getvalue())
    assert parsed["mcpServers"]["codegraphkb"]["command"] == "codegraph"


def test_install_assistant_writes_when_requested(tmp_path: Path) -> None:
    cfg = tmp_path / "claude.json"
    result = install_assistant(
        "claude",
        tmp_path,
        write=True,
        config_path=cfg,
    )
    assert result.written
    assert cfg.exists()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["mcpServers"]["codegraphkb"]["command"] == "codegraph"


def test_install_assistant_merges_with_existing_servers(tmp_path: Path) -> None:
    cfg = tmp_path / "claude.json"
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "other-server": {"command": "other", "args": []},
                }
            }
        ),
        encoding="utf-8",
    )

    install_assistant("claude", tmp_path, write=True, config_path=cfg)

    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert "other-server" in data["mcpServers"]
    assert "codegraphkb" in data["mcpServers"]


def test_install_assistant_handles_corrupt_existing_config(tmp_path: Path) -> None:
    cfg = tmp_path / "claude.json"
    cfg.write_text("not-json", encoding="utf-8")

    result = install_assistant("claude", tmp_path, write=True, config_path=cfg)

    assert result.written
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["mcpServers"]["codegraphkb"]["command"] == "codegraph"


def test_merge_into_existing_creates_mcp_servers_key_when_missing(tmp_path: Path) -> None:
    cfg = tmp_path / "cursor.json"
    cfg.write_text(json.dumps({"otherKey": True}), encoding="utf-8")
    merged = merge_into_existing(
        cfg,
        {"mcpServers": {"codegraphkb": {"command": "codegraph", "args": []}}},
    )
    assert merged["otherKey"] is True
    assert "codegraphkb" in merged["mcpServers"]


def test_uninstall_removes_codegraphkb_entry(tmp_path: Path) -> None:
    cfg = tmp_path / "claude.json"
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "codegraphkb": {"command": "codegraph", "args": []},
                    "other": {"command": "other", "args": []},
                }
            }
        ),
        encoding="utf-8",
    )

    result = uninstall_assistant("claude", config_path=cfg)

    assert result.written
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert "codegraphkb" not in data["mcpServers"]
    assert "other" in data["mcpServers"]


def test_uninstall_is_noop_when_config_missing(tmp_path: Path) -> None:
    cfg = tmp_path / "absent.json"
    result = uninstall_assistant("claude", config_path=cfg)
    assert not result.written


def test_install_cli_print_only_emits_json(tmp_path: Path) -> None:
    try:
        runner = CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        runner = CliRunner()
    result = runner.invoke(cli, ["install", "claude", "--repo", str(tmp_path), "--print"])
    assert result.exit_code == 0, result.output
    out = getattr(result, "stdout", None) or result.output
    # Strip non-JSON note lines (e.g. "Suggested location: ...") in case they ended up here.
    json_part = out.split("\n}", 1)
    body = json_part[0] + "\n}" if len(json_part) == 2 else out
    parsed = json.loads(body)
    assert "mcpServers" in parsed


def test_install_cli_writes_with_yes(tmp_path: Path) -> None:
    runner = CliRunner()
    cfg = tmp_path / "claude.json"
    result = runner.invoke(
        cli,
        [
            "install", "claude",
            "--repo", str(tmp_path),
            "--yes",
            "--config", str(cfg),
        ],
    )
    assert result.exit_code == 0, result.output
    assert cfg.exists()
