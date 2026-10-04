import pytest

from pi_mono.durable import MemoryStorage, ReadAfterWrite, create_session, define_doc


@pytest.mark.anyio
async def test_memory_storage_prepared_commit_is_idempotent_and_isolated() -> None:
    storage = MemoryStorage()
    prepared = storage.prepare_commit([{"type": "conversation", "value": {"id": 1, "data": {"items": [1]}}}])
    assert prepared.apply() == 1
    assert prepared.apply() == 1
    stored = await storage.conversation(1)
    stored["data"]["items"].append(2)
    assert (await storage.conversation(1))["data"] == {"items": [1]}


@pytest.mark.anyio
async def test_session_commits_tables_documents_and_read_fence() -> None:
    session = create_session(MemoryStorage())
    notes = define_doc({"kind": "notes", "version": 1, "scope": "conversation", "history": "rewindable", "fork": "asOf", "initial": lambda: {"text": ""}})

    async def change(tx):
        conversation = await tx.create_conversation()
        await tx.append_entry(conversation["id"], {"kind": "note", "data": "one"})
        with pytest.raises(ReadAfterWrite): await tx.conversation(conversation["id"])
        (await tx.doc(notes, conversation["id"]))["text"] = "saved"
        return conversation["id"]

    conversation_id = await session.commit(change)
    assert await session.snapshot(notes, conversation_id) == {"text": "saved"}
