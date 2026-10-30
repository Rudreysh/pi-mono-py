# TypeScript Fork and Python Port Workflow

## Target Layout

Keep two permanent local checkouts, one per implementation:

```text
/Users/rukesh/Documents/projects/learning/
  pi-mono/       Original TypeScript and personal TypeScript features
  pi-mono-py/    Python implementation, tests, and port tracking
```

This replaces the earlier recommendation to edit Python inside the monorepo
and copy it into a publication clone. After migration, develop and publish
Python directly from its standalone repository.

| Repository | Remote in local checkout | Purpose |
|------------|--------------------------|---------|
| Original TypeScript repository | `upstream` in `pi-mono` | Fetch and read the owner's source |
| https://github.com/Rudreysh/pi-mono | `my_fork` in `pi-mono` | Store the upstream mirror and personal TypeScript branches |
| https://github.com/Rudreysh/pi-mono-py | `origin` in `pi-mono-py` | Develop and publish Python |

Normal pushes target your repositories. This workflow does not open pull
requests against the owner's repository.

## Branch Roles

| Checkout | Branch | Purpose |
|----------|--------|---------|
| TypeScript | `main` | Exact mirror of the last fetched upstream main |
| TypeScript | `ts-custom` | Your TypeScript features plus periodic upstream merges |
| TypeScript | `feature/<name>` | Optional feature branch from ts-custom |
| Python | `develop` | Python development, ports, and personal Python features |
| Python | `main` | Verified stable Python code |
| Python | `port/<name>` | Optional branch for a substantial port |

The current TypeScript `develop` contains the historical Python port. Preserve
it during migration. Create `ts-custom` from the clean TypeScript `main`, then
bring across any reviewed personal TypeScript changes needed from old branches.

One checkout shows one branch at a time. Switch TypeScript to `main` to read the
original and to `ts-custom` to work on your features. Git history retains other
versions without requiring extra folders.

## One-Time Migration

The following checklist describes the one-time migration. The October 30, 2026
migration reconciles `pi-mono/python` into `pi-mono-py` and adapts its catalog
scripts and optional TypeScript bridge for sibling checkouts. The original
working tree and pre-migration standalone repository are preserved under
`/Users/rukesh/Documents/projects/pi-port-backups/2026-10-30-migration`.
Edit Python in `pi-mono-py` after this migration.

1. Coordinate with other editing sessions. Inventory tracked, untracked, and
   ignored files in both Python copies and record their commits.
2. Preserve unique work from both copies. Review and test coherent batches;
   commit explicit file paths after checking the index. Check session exports
   and credentials before including new files.
3. Reconcile the latest implementation into `pi-mono-py` on `develop`.
   Preserve standalone CI, package metadata, and useful history. Review removals
   individually; avoid blind synchronization with `--delete`.
4. Adapt path-dependent scripts, tests, and CI. The current model generator
   assumes a `python/` directory inside the TypeScript repository. Give it an
   explicit sibling TypeScript source path before relying on standalone use.
5. Test affected behavior from `pi-mono-py`, verify CLI startup with fake or
   offline inputs, and push reviewed Python commits to its `origin`.
6. Verify the remote contents. From then on, edit Python only in `pi-mono-py`.
   Preserve the old monorepo branch until reconciliation is verified.
7. With work preserved, use TypeScript `main` or `ts-custom` in `pi-mono`.
   Those upstream-based branches do not need the embedded Python tree. Remove
   leftover untracked files only after verifying their migrated contents.
8. Retire clean `pi-mono-upstream` using `git worktree remove`. Retire the
   older `pi-mono-python` clone after checking unique commits and ignored data.

Legacy copying scripts are not part of the target workflow:
`scripts/push-python-to-github.sh` in the monorepo and
`scripts/sync-from-monorepo.sh` in the standalone repo. The former copies live
files before switching branches and stages every destination change. Use
reviewed migration steps instead of running either script routinely.

## Periodically Update TypeScript

Use these commands only with a clean checkout and after coordinating with
other sessions before branch switches. Stop on a failed command.

```bash
cd /Users/rukesh/Documents/projects/learning/pi-mono
git status --short
git fetch upstream main
git switch main
git merge --ff-only upstream/main
git push my_fork main
git rev-parse HEAD
```

If `git status --short` shows work, preserve it before switching or merging.
If fast-forwarding fails, inspect divergence; do not reset or force-push.
After success, local TypeScript `main` and your GitHub `main` match the fetched
original commit.

On October 30, 2026, upstream and fork main were verified at
`50af8c160153e3721a18b1a046a4adf201635861`. This records a reference rather than
claiming it will always be the newest commit.

Create your custom branch once, after migration and the mirror update:

```bash
git switch -c ts-custom main
git push -u my_fork ts-custom
```

After later mirror updates, with a clean checkout:

```bash
git switch ts-custom
git merge main
```

Resolve and review conflicts, test affected behavior, run `npm run check`,
then push `ts-custom` to `my_fork`. Coordinate conflicts involving another
session's changes. The custom branch is expected to differ from the original.

Implement new TypeScript features on `ts-custom` or on a feature branch created
from it. Commit explicit reviewed paths and push to your fork. Feature branches
can be merged locally into `ts-custom`; no upstream pull request is needed.
Keep personal changes off the mirror branch.

## Port and Publish Python

The Python repository has independent Git history. Read TypeScript in the
sibling checkout and implement corresponding Python behavior; do not merge the
TypeScript repository into the Python repository.

1. Record the exact upstream commit inspected in Python's `docs/parity.md`.
   Track the last reviewed revision separately from per-feature implementation
   revisions. A reviewed release can still have unported features.
2. Compare the previously reviewed hash to TypeScript `main` with `git log`
   and `git diff` restricted to relevant packages. Read upstream tests.
3. List features as implemented, partial, missing, or intentionally different.
   Track personal TypeScript additions separately from upstream parity.
4. Port one coherent feature and translate meaningful tests. Use fake providers
   for automated request tests unless live verification was explicitly requested.
5. Run affected Python tests, appropriate Python lint/type checks, and
   `git diff --check`. Run `npm run check` in the TypeScript checkout when
   TypeScript code changes; Python has no root npm workflow.
6. Update parity notes, review the diff, commit explicit paths, and push Python
   `develop` directly to `origin`. There is no copy or export step.
7. Promote verified Python work to Python `main` for a stable version.

Example commands after migration, from a clean Python checkout:

```bash
cd /Users/rukesh/Documents/projects/learning/pi-mono-py
git switch develop
git pull --ff-only origin develop
source .venv/bin/activate
PYTHONPATH=src python -m pytest tests/test_cursor.py
git diff --check
```

Choose tests matching the feature. Review `git status` and `git diff`, stage
explicit paths, and commit. Then publish:

```bash
git push origin develop
```

Promote verified Python work from a clean checkout:

```bash
git switch main
git pull --ff-only origin main
git merge develop
git push origin main
git switch develop
```

Reconcile unexpected remote changes before retrying a rejected push. Do not
force-push as part of this workflow.

## Repeating Cycle

```text
Original TypeScript GitHub
    -> fetch -> local TypeScript main -> push -> your TypeScript GitHub main
                      |
                      +-> merge -> ts-custom -> push -> your custom TS branch
                      |
                      +-> read and port -> local Python develop
                                              |
                                              +-> test -> push -> Python GitHub
```

Keep only `pi-mono` and `pi-mono-py` as permanent project folders. Use branches
and commits for versions. Archive other local copies only after reconciliation;
archiving a local copy does not delete its GitHub repository.
