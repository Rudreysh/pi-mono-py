"""Ports of TypeScript v0.83–v0.85 behavior."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from pi_mono.agent.agent import Agent
from pi_mono.agent.agent_loop import create_error_tool_result
from pi_mono.agent.harness.skills import _load_skill_from_file
from pi_mono.agent.harness.system_prompt import format_skills_for_system_prompt
from pi_mono.agent.harness.env.local import LocalExecutionEnv
from pi_mono.coding_agent.cli.args import parse_args
from pi_mono.coding_agent.cli.auth_command import parse_auth_command, AuthCommandError
from pi_mono.coding_agent.core.resource_loader import _load_context_file_from_dir
from pi_mono.coding_agent.core.system_prompt import build_system_prompt
from pi_mono.coding_agent.core.tools.edit import _prepare_edit_arguments
from pi_mono.coding_agent.core.tools.path_utils import resolve_execution_cwd
from pi_mono.coding_agent.core.tools.write import execute_write
from pi_mono.coding_agent.modes.json_event import to_json_event
from pi_mono.core.session_manager import SessionManager
from pi_mono.core.settings_manager import SettingsManager
from pi_mono.utils.node_http_proxy import resolve_http_proxy_url_for_target


def test_resolve_execution_cwd_prefers_ctx():
    @dataclass
    class Ctx:
        cwd: str

    assert resolve_execution_cwd("/default") == "/default"
    assert resolve_execution_cwd("/default", Ctx("/from-ctx")) == "/from-ctx"
    assert resolve_execution_cwd("/default", {"cwd": "/from-dict"}) == "/from-dict"
    assert resolve_execution_cwd("/default", {"cwd": ""}) == "/default"


def test_edit_coerces_single_object_and_json_object_string():
    wrapped = _prepare_edit_arguments(
        {"path": "a.py", "edits": {"oldText": "a", "newText": "b"}}
    )
    assert wrapped["edits"] == [{"oldText": "a", "newText": "b"}]

    parsed = _prepare_edit_arguments(
        {"path": "a.py", "edits": json.dumps({"oldText": "a", "newText": "b"})}
    )
    assert parsed["edits"] == [{"oldText": "a", "newText": "b"}]


@pytest.mark.asyncio
async def test_write_success_message_omits_byte_count(tmp_path: Path):
    target = tmp_path / "out.txt"
    result = await execute_write(str(tmp_path), str(target), "hello")
    text = result["content"][0]["text"]
    assert text == f"Successfully wrote to {target}"
    assert "bytes" not in text


def test_skills_prompt_uses_bash_when_read_is_absent():
    skills = [
        {
            "name": "demo",
            "description": "Demo skill",
            "filePath": "/skills/demo/SKILL.md",
        }
    ]
    prompt = build_system_prompt(
        selected_tools=["bash", "edit", "write"],
        cwd="/tmp",
        skills=skills,  # type: ignore[arg-type]
    )
    assert "Use bash to load a skill's file" in prompt
    assert "Use the read tool to load a skill's file" not in prompt
    assert format_skills_for_system_prompt(skills, "bash").startswith("\n\n")


def test_agents_override_preferred_and_bom_stripped(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("from agents.md", encoding="utf-8")
    (tmp_path / "AGENTS.override.md").write_text(
        "\ufefffrom override", encoding="utf-8"
    )
    loaded = _load_context_file_from_dir(str(tmp_path))
    assert loaded is not None
    assert loaded["path"].endswith("AGENTS.override.md")
    assert loaded["content"] == "from override"


@pytest.mark.asyncio
async def test_root_readme_without_skill_frontmatter_is_silent(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Project\n\nNot a skill.\n", encoding="utf-8")
    env = LocalExecutionEnv(cwd=str(tmp_path))
    result = await _load_skill_from_file(env, str(tmp_path / "README.md"))
    assert result["skill"] is None
    assert result["diagnostics"] == []


def test_cli_end_of_options_treats_flags_as_messages():
    parsed = parse_args(["--", "--help", "@notes.md", "hello"])
    assert parsed.help is False
    assert parsed.messages == ["--help", "hello"]
    assert parsed.file_args == ["notes.md"]


def test_auth_command_parse():
    command = parse_auth_command(["auth", "check", "--provider", "openai", "--json"])
    assert command is not None
    assert command.kind == "check"
    assert command.json is True
    assert command.args == ["--provider", "openai"]
    with pytest.raises(AuthCommandError):
        parse_auth_command(["auth", "nope"])


def test_json_message_update_strips_cumulative_message():
    event = {
        "type": "message_update",
        "message": {
            "role": "assistant",
            "usage": {"input": 1, "output": 2},
            "content": [{"type": "toolCall", "id": "call-1", "name": "bash", "arguments": {}}],
        },
        "assistantMessageEvent": {
            "type": "toolcall_start",
            "contentIndex": 0,
            "partial": {
                "content": [{"type": "toolCall", "id": "call-1", "name": "bash", "arguments": {}}]
            },
        },
    }
    wired = to_json_event(event)
    assert "message" not in wired
    assert wired["usage"] == {"input": 1, "output": 2}
    assert wired["assistantMessageEvent"]["id"] == "call-1"
    assert wired["assistantMessageEvent"]["toolName"] == "bash"
    assert "partial" not in wired["assistantMessageEvent"]


def test_blocked_tool_terminate_flag():
    result = create_error_tool_result("blocked", terminate=True)
    assert result["terminate"] is True
    assert result["content"][0]["text"] == "blocked"


def test_agent_reset_refuses_while_active():
    agent = Agent()
    agent.active_run = {"abort_controller": object(), "future": object()}  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="already processing"):
        agent.reset()
    agent.active_run = None
    agent.reset()
    assert agent.state.messages == []


def test_default_tools_setting():
    manager = SettingsManager.in_memory({"defaultTools": ["grep", "find"]})
    assert manager.get_default_tools() == ["grep", "find"]


def test_branched_session_rewrites_compaction_first_kept_entry_id(tmp_path: Path):
    manager = SessionManager.create(str(tmp_path), str(tmp_path / "sessions"))
    user_id = manager.append_message(
        {"role": "user", "content": [{"type": "text", "text": "hi"}], "timestamp": 1}
    )
    label_id = manager.append_label_change(user_id, "keep")
    next_user_id = manager.append_message(
        {"role": "user", "content": [{"type": "text", "text": "next"}], "timestamp": 2}
    )
    compaction_id = manager.append_compaction("summary", label_id, 100)
    leaf_id = manager.append_message(
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "timestamp": 3,
        }
    )
    manager.create_branched_session(str(leaf_id))
    compaction = next(entry for entry in manager.get_entries() if entry.get("type") == "compaction")
    assert compaction["id"] == compaction_id
    assert compaction["firstKeptEntryId"] == next_user_id
    assert compaction["firstKeptEntryId"] != label_id


def test_no_proxy_matches_root_and_subdomain(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("NO_PROXY", "example.com, .wildcard.org, *.star.net")
    monkeypatch.delenv("https_proxy", raising=False)
    assert resolve_http_proxy_url_for_target("https://example.com") is None
    assert resolve_http_proxy_url_for_target("https://api.example.com") is None
    assert resolve_http_proxy_url_for_target("https://wildcard.org") is None
    assert resolve_http_proxy_url_for_target("https://api.wildcard.org") is None
    assert resolve_http_proxy_url_for_target("https://star.net") is None
    assert resolve_http_proxy_url_for_target("https://api.star.net") is None
    assert resolve_http_proxy_url_for_target("https://notexample.com") is not None
