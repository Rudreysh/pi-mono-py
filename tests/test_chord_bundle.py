import base64
import hashlib
import json

import pytest

from pi_mono.chord import create_facet_bundle_loader, read_facet_bundle_artifact, read_facet_bundle_manifest


def _integrity(source: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(source.encode()).digest()).decode()


@pytest.mark.anyio
async def test_python_facet_bundle_validates_integrity_and_loads_facets(tmp_path) -> None:
    source = "from pi_mono.chord import define_facet\nfacets = [define_facet({'id': 'bundle', 'setup': lambda env: None})]\n"
    (tmp_path / "facet.py").write_text(source)
    (tmp_path / "chord-facets.json").write_text(json.dumps({"format": "chord.facet-bundle", "formatVersion": 2, "plugin": {"id": "test.plugin"}, "entries": {"main": {"file": "facet.py", "integrity": _integrity(source), "externalImports": []}}}))
    manifest = read_facet_bundle_manifest(tmp_path / "chord-facets.json")
    assert manifest["plugin"]["id"] == "test.plugin"
    assert read_facet_bundle_artifact(tmp_path / "chord-facets.json", "main")["source"] == source
    loaded = await create_facet_bundle_loader(manifest_path=tmp_path / "chord-facets.json", entry="main").load()
    assert [facet.id for facet in loaded.facets] == ["bundle"]


@pytest.mark.anyio
async def test_facet_bundle_rejects_tampered_source(tmp_path) -> None:
    source = "facets = []\n"
    (tmp_path / "facet.py").write_text(source + "# changed\n")
    (tmp_path / "chord-facets.json").write_text(json.dumps({"format": "chord.facet-bundle", "formatVersion": 2, "plugin": {"id": "test.plugin"}, "entries": {"main": {"file": "facet.py", "integrity": _integrity(source), "externalImports": []}}}))
    with pytest.raises(RuntimeError, match="integrity"):
        await create_facet_bundle_loader(manifest_path=tmp_path / "chord-facets.json", entry="main").load()
