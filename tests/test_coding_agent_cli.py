from pi_mono.coding_agent.cli.args import parse_args


def test_parse_args_help_and_version():
    help_args = parse_args(["--help"])
    assert help_args.help is True

    version_args = parse_args(["-v"])
    assert version_args.version is True


def test_parse_args_print_mode_and_messages():
    parsed = parse_args(["-p", "hello", "world"])
    assert parsed.print_mode is True
    assert parsed.messages == ["hello", "world"]


def test_parse_args_tools_and_thinking():
    parsed = parse_args(
        [
            "--tools",
            "read,grep,ls",
            "--thinking",
            "high",
            "--provider",
            "faux",
            "--model",
            "faux-1",
        ]
    )
    assert parsed.tools == ["read", "grep", "ls"]
    assert parsed.thinking == "high"
    assert parsed.provider == "faux"
    assert parsed.model == "faux-1"


def test_parse_args_invalid_short_option():
    parsed = parse_args(["-z"])
    assert any(item["type"] == "error" for item in parsed.diagnostics)


def test_parse_args_file_args():
    parsed = parse_args(["@README.md", "summarize this"])
    assert parsed.file_args == ["README.md"]
    assert parsed.messages == ["summarize this"]


def test_load_configured_skills_accepts_object_diagnostics(tmp_path):
    import asyncio

    from pi_mono.coding_agent.core.skills import load_configured_skills

    skills_dir = tmp_path / "skills" / "broken"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("not valid frontmatter\n", encoding="utf-8")

    async def run():
        result = await load_configured_skills(
            cwd=str(tmp_path),
            agent_dir=str(tmp_path / "agent"),
            skill_paths=[str(tmp_path / "skills")],
        )
        assert "diagnostics" in result
        return result

    result = asyncio.run(run())
    assert isinstance(result["diagnostics"], list)


def test_read_piped_stdin_nonblocking_without_data(monkeypatch):
    import asyncio
    from io import StringIO

    from pi_mono.coding_agent.main import _read_piped_stdin

    monkeypatch.setattr("sys.stdin", StringIO())
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)  # type: ignore[method-assign]

    assert asyncio.run(_read_piped_stdin()) is None
