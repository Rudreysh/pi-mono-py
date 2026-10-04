import json

from pi_mono.core.session_manager import SessionManager


def _roles(path):
    with open(path, encoding="utf-8") as session_file:
        entries = [json.loads(line) for line in session_file if line.strip()]
    return [entry.get("message", {}).get("role", entry["type"]) for entry in entries]


def test_session_file_is_created_at_first_user_message(tmp_path):
    manager = SessionManager.create(str(tmp_path), str(tmp_path / "sessions"))
    session_file = manager.get_session_file()
    assert session_file is not None

    manager.append_model_change("openai", "gpt-5")
    assert not list((tmp_path / "sessions").glob("*.jsonl"))

    manager.append_message({"role": "user", "content": "first prompt"})

    assert _roles(session_file) == ["session", "model_change", "user"]


def test_session_file_appends_entries_after_first_user_message(tmp_path):
    manager = SessionManager.create(str(tmp_path), str(tmp_path / "sessions"))
    session_file = manager.get_session_file()
    assert session_file is not None

    manager.append_message({"role": "user", "content": "first prompt"})
    manager.append_custom_entry("preset-state", {"name": "plan"})
    manager.append_message({"role": "assistant", "content": [{"type": "text", "text": "answer"}]})

    assert _roles(session_file) == ["session", "user", "custom", "assistant"]


def test_branched_session_persists_when_history_has_a_user_message(tmp_path):
    manager = SessionManager.create(str(tmp_path), str(tmp_path / "sessions"))
    user_entry_id = manager.append_message({"role": "user", "content": "first prompt"})

    branched_file = manager.create_branched_session(user_entry_id)

    assert branched_file is not None
    assert _roles(branched_file) == ["session", "user"]
