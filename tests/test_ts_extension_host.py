import asyncio
import sys
import time

import pytest

from pi_mono.coding_agent.core.extensions import ts_extension_loader as loader


def test_ts_host_request_fails_quickly_when_process_exits(monkeypatch):
    host = loader.TsExtensionHost()
    monkeypatch.setattr(loader.TsExtensionHost, "is_available", staticmethod(lambda: True))
    original_exec = asyncio.create_subprocess_exec

    async def fake_exec(*_args, **kwargs):
        return await original_exec(
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('host boom\\n'); sys.exit(1)",
            stdin=kwargs.get("stdin"),
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    async def run() -> None:
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="host boom|exited"):
            await host.request("load", {"path": "missing.ts"})
        assert time.monotonic() - started < 5
        await host.stop()

    asyncio.run(run())


def test_load_ts_extensions_does_not_hang_when_host_crashes(monkeypatch):
    monkeypatch.setattr(loader.TsExtensionHost, "is_available", staticmethod(lambda: True))
    original_exec = asyncio.create_subprocess_exec

    async def fake_exec(*_args, **kwargs):
        return await original_exec(
            sys.executable,
            "-c",
            "import sys; sys.exit(1)",
            stdin=kwargs.get("stdin"),
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    loader._host = None

    async def run() -> None:
        started = time.monotonic()
        _extensions, errors = await asyncio.wait_for(
            loader.load_ts_extensions(["ext.ts"], "/tmp"),
            timeout=5,
        )
        assert time.monotonic() - started < 5
        assert errors
        assert "Failed to load TypeScript extension" in errors[0]["error"]
        if loader._host is not None:
            await loader._host.stop()
            loader._host = None

    asyncio.run(run())
