"""Verify external source access without an embedded monorepo Python tree."""

import json
import subprocess
import sys
from pathlib import Path

from pi_mono.coding_agent.core.extensions import ts_extension_loader


def test_catalog_sync_targets_standalone_checkout(tmp_path):
    typescript = tmp_path / "typescript"
    package = typescript / "packages" / "ai" / "src"
    package.mkdir(parents=True)
    python = tmp_path / "python-repo"
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        from sync_models import sync_models

        for stem in ("models.generated", "image-models.generated"):
            (package / f"{stem}.json").write_text(json.dumps({"test": {"id": "model"}}))
        assert sync_models(typescript_root=typescript, python_root=python) == 0
        assert sync_models(check=True, typescript_root=typescript, python_root=python) == 0
        assert not (typescript / "python").exists()
        (package / "models.generated.json").write_text("{}")
        assert sync_models(check=True, typescript_root=typescript, python_root=python) == 1
    finally:
        sys.path.remove(str(scripts))


def test_catalog_wrapper_accepts_external_typescript_root():
    script = Path(__file__).resolve().parents[1] / "scripts" / "generate_models.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help"], capture_output=True, text=True, check=True
    )
    assert result.returncode == 0
    assert "--typescript-root" in result.stdout


def test_typescript_bridge_script_is_in_standalone_repo():
    assert (
        ts_extension_loader._HOST_SCRIPT
        == Path(__file__).resolve().parents[1] / "scripts" / "ts_extension_host.mjs"
    )
    assert ts_extension_loader._HOST_SCRIPT.is_file()
