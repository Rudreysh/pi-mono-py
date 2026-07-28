"""Tests for agent harness tools."""

from pathlib import Path

import pytest

from pi_mono.agent.harness.env.local import LocalExecutionEnv
from pi_mono.agent.harness.tools import (
    ExecutionToolContext,
    create_bash_tool,
    create_edit_tool,
    create_read_tool,
    create_write_tool,
)
from pi_mono.agent.harness.tools.path_utils import resolve_tool_path


def _make_ctx(tmp_path: Path) -> ExecutionToolContext:
    return ExecutionToolContext(env=LocalExecutionEnv(str(tmp_path)))


@pytest.mark.anyio
async def test_create_factories_exist():
    bash = create_bash_tool()
    read = create_read_tool()
    edit = create_edit_tool()
    write = create_write_tool()

    assert bash.name == "bash"
    assert read.name == "read"
    assert edit.name == "edit"
    assert write.name == "write"

    for tool in (bash, read, edit, write):
        assert hasattr(tool, "execute")
        assert hasattr(tool, "description")
        assert hasattr(tool, "parameters")


@pytest.mark.anyio
async def test_resolve_tool_path_relative(tmp_path: Path):
    env = LocalExecutionEnv(str(tmp_path))
    resolved = await resolve_tool_path(env, "foo/bar.txt")
    assert resolved == str(tmp_path / "foo" / "bar.txt")


@pytest.mark.anyio
async def test_resolve_tool_path_absolute(tmp_path: Path):
    env = LocalExecutionEnv(str(tmp_path))
    resolved = await resolve_tool_path(env, "/absolute/path.txt")
    assert resolved == "/absolute/path.txt"


@pytest.mark.anyio
async def test_resolve_tool_path_strips_at_prefix(tmp_path: Path):
    env = LocalExecutionEnv(str(tmp_path))
    resolved = await resolve_tool_path(env, "@some/file.txt")
    assert resolved == str(tmp_path / "some" / "file.txt")


@pytest.mark.anyio
async def test_write_and_read_roundtrip(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    write_tool = create_write_tool()
    read_tool = create_read_tool()

    result = await write_tool.execute(
        "call-1",
        {"path": "test.txt", "content": "hello harness\nsecond line"},
        context=ctx,
    )
    assert "Successfully wrote" in result["content"][0]["text"]
    assert (tmp_path / "test.txt").read_text() == "hello harness\nsecond line"

    result = await read_tool.execute(
        "call-2",
        {"path": "test.txt"},
        context=ctx,
    )
    text = result["content"][0]["text"]
    assert "hello harness" in text
    assert "second line" in text


@pytest.mark.anyio
async def test_write_creates_parent_dirs(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    write_tool = create_write_tool()
    await write_tool.execute(
        "call-1",
        {"path": "deep/nested/dir/file.txt", "content": "nested"},
        context=ctx,
    )
    assert (tmp_path / "deep" / "nested" / "dir" / "file.txt").read_text() == "nested"


@pytest.mark.anyio
async def test_edit_tool(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    (tmp_path / "edit_me.txt").write_text("alpha beta gamma\n", encoding="utf-8")

    edit_tool = create_edit_tool()
    result = await edit_tool.execute(
        "call-1",
        {"path": "edit_me.txt", "edits": [{"oldText": "beta", "newText": "BETA"}]},
        context=ctx,
    )
    assert "Successfully replaced" in result["content"][0]["text"]
    assert (tmp_path / "edit_me.txt").read_text() == "alpha BETA gamma\n"


@pytest.mark.anyio
async def test_edit_tool_not_found_error(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    (tmp_path / "exists.txt").write_text("some content\n", encoding="utf-8")

    edit_tool = create_edit_tool()
    with pytest.raises(ValueError, match="Could not find"):
        await edit_tool.execute(
            "call-1",
            {"path": "exists.txt", "edits": [{"oldText": "nonexistent text", "newText": "x"}]},
            context=ctx,
        )


@pytest.mark.anyio
async def test_read_with_offset_limit(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    lines = "\n".join(f"line {i}" for i in range(1, 21))
    (tmp_path / "multi.txt").write_text(lines, encoding="utf-8")

    read_tool = create_read_tool()
    result = await read_tool.execute(
        "call-1",
        {"path": "multi.txt", "offset": 5, "limit": 3},
        context=ctx,
    )
    text = result["content"][0]["text"]
    assert "line 5" in text
    assert "line 7" in text


@pytest.mark.anyio
async def test_tool_requires_context():
    write_tool = create_write_tool()
    with pytest.raises(RuntimeError, match="requires an ExecutionToolContext"):
        await write_tool.execute("call-1", {"path": "x.txt", "content": "y"})
