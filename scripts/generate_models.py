#!/usr/bin/env python3
"""Generate Python model catalogs from the TypeScript ai package."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from sync_models import _repo_root, sync_models


def generate_models(
    *, run_ts_generate: bool = False, check: bool = False, typescript_root: Path | None = None
) -> int:
    if run_ts_generate:
        root = typescript_root or _repo_root()
        ai_package = root / "packages" / "ai"
        subprocess.run(["npm", "run", "generate-models"], cwd=ai_package, check=True)
    if typescript_root is not None:
        return sync_models(check=check, typescript_root=typescript_root)
    return sync_models(check=check)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--typescript-root",
        type=Path,
        help="TypeScript checkout (defaults to PI_MONO_ROOT or sibling pi-mono).",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Run the TypeScript generate-models scripts before syncing JSON catalogs.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if Python catalogs differ from the TypeScript sources.",
    )
    args = parser.parse_args()
    try:
        raise SystemExit(
            generate_models(
                run_ts_generate=args.generate,
                check=args.check,
                typescript_root=args.typescript_root,
            )
        )
    except subprocess.CalledProcessError as error:
        print(f"generate-models failed: {error}", file=sys.stderr)
        raise SystemExit(error.returncode or 1) from error


if __name__ == "__main__":
    main()
