"""Facet bundle manifest validation and Python-native facet loading."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from .facets import LoadedFacets

FACET_BUNDLE_FORMAT = "chord.facet-bundle"
FACET_BUNDLE_FORMAT_VERSION = 2
FACET_BUNDLE_MANIFEST_FILE = "chord-facets.json"
FACET_BUNDLE_ARTIFACT_FORMAT = "chord.facet-bundle-artifact"
FACET_BUNDLE_ARTIFACT_FORMAT_VERSION = 2


def read_facet_bundle_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as error:
        raise RuntimeError(f"Could not read facet bundle manifest {manifest_path}") from error
    if not isinstance(value, dict) or value.get("format") != FACET_BUNDLE_FORMAT or value.get("formatVersion") != FACET_BUNDLE_FORMAT_VERSION:
        raise ValueError("Invalid facet bundle manifest format")
    plugin, entries = value.get("plugin"), value.get("entries")
    if not isinstance(plugin, dict) or not isinstance(plugin.get("id"), str) or not plugin["id"] or not isinstance(entries, dict):
        raise ValueError("Invalid facet bundle manifest")
    for name, entry in entries.items():
        if not isinstance(name, str) or not name or not isinstance(entry, dict):
            raise ValueError("Invalid facet bundle entry")
        _validate_entry(entry)
    return value


def read_facet_bundle_artifact(manifest_path: str | Path, entry_name: str) -> dict[str, Any]:
    manifest_file = Path(manifest_path).resolve()
    manifest = read_facet_bundle_manifest(manifest_file)
    entry = _entry(manifest, entry_name)
    source = _bundle_file(manifest_file, entry["file"]).read_text(encoding="utf-8")
    _verify_source(source, entry)
    artifact = {"format": FACET_BUNDLE_ARTIFACT_FORMAT, "formatVersion": FACET_BUNDLE_ARTIFACT_FORMAT_VERSION, "plugin": manifest["plugin"], "entryName": entry_name, "entry": entry, "source": source}
    if entry.get("sourceMap"):
        artifact["sourceMapContents"] = _bundle_file(manifest_file, entry["sourceMap"]).read_text(encoding="utf-8")
    return artifact


class FacetBundleLoader:
    def __init__(self, manifest_path: str | Path, entry: str, verify_integrity: bool = True) -> None:
        if not entry:
            raise TypeError("Facet bundle entry name must not be empty")
        self._manifest_path, self._entry, self._verify = Path(manifest_path).resolve(), entry, verify_integrity

    async def load(self) -> LoadedFacets:
        manifest = read_facet_bundle_manifest(self._manifest_path)
        entry = _entry(manifest, self._entry)
        module_path = _bundle_file(self._manifest_path, entry["file"])
        if module_path.suffix != ".py":
            raise RuntimeError("Python facet loader supports only .py bundle entries; execute .cjs entries in Node")
        source = module_path.read_text(encoding="utf-8")
        if self._verify:
            _verify_source(source, entry)
        module = _load_module(module_path, f"pi_mono_chord_bundle_{hashlib.sha256(source.encode()).hexdigest()}")
        exported = getattr(module, "facets", getattr(module, "default", None))
        facets = exported() if callable(exported) else exported
        if not isinstance(facets, list):
            facets = [facets]
        if not facets or any(not hasattr(facet, "id") or not hasattr(facet, "setup") for facet in facets):
            raise RuntimeError(f"Facet bundle entry {manifest['plugin']['id']}/{self._entry} did not export facets")

        async def dispose() -> None:
            return None

        return LoadedFacets(facets, dispose)


def create_facet_bundle_loader(*, manifest_path: str | Path, entry: str, verify_integrity: bool = True) -> FacetBundleLoader:
    return FacetBundleLoader(manifest_path, entry, verify_integrity)


def _validate_entry(entry: dict[str, Any]) -> None:
    if not isinstance(entry.get("file"), str) or not isinstance(entry.get("integrity"), str) or not isinstance(entry.get("externalImports"), list):
        raise ValueError("Invalid facet bundle entry")
    if any(not isinstance(value, str) for value in entry["externalImports"]):
        raise ValueError("Invalid facet bundle external imports")
    _safe_name(entry["file"])
    if entry.get("sourceMap") is not None:
        _safe_name(entry["sourceMap"])


def _entry(manifest: dict[str, Any], name: str) -> dict[str, Any]:
    entry = manifest["entries"].get(name)
    if entry is None:
        raise RuntimeError(f"Facet bundle {manifest['plugin']['id']} has no entry named {name}")
    return entry


def _bundle_file(manifest_path: Path, filename: str) -> Path:
    _safe_name(filename)
    return manifest_path.parent / filename


def _safe_name(value: str) -> None:
    if not value or Path(value).name != value or value in {".", ".."}:
        raise ValueError("Facet bundle file must be a filename relative to its manifest")


def _verify_source(source: str, entry: dict[str, Any]) -> None:
    prefix = "sha256-"
    integrity = entry["integrity"]
    if not integrity.startswith(prefix):
        raise ValueError("Facet bundle entry has an invalid SHA-256 integrity value")
    actual = base64.b64encode(hashlib.sha256(source.encode("utf-8")).digest()).decode("ascii")
    if actual != integrity[len(prefix):]:
        raise RuntimeError(f"Facet bundle integrity check failed for {entry['file']}")


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load facet bundle module {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
