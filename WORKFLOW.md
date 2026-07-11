# Python port workflow

This `python/` folder is the Python port of the TypeScript pi-mono codebase.
It is the **only** part of this local repo that is yours to change and publish.

## Repos

| What | Where |
| --- | --- |
| Local monorepo (TS + Python) | `~/Documents/projects/learning/pi-mono` |
| Python source (edit here) | `~/Documents/projects/learning/pi-mono/python/` |
| Python on GitHub (push here) | https://github.com/Rudreysh/pi-mono-py |
| Upstream TypeScript (read only) | https://github.com/earendil-works/pi |

## Rules

1. **Edit Python in** `pi-mono/python/`
2. **Push Python to** `Rudreysh/pi-mono-py` only
3. **Do not push Python** to `Rudreysh/pi-mono` or open PRs to `earendil-works/pi`
4. **Keep TypeScript in sync** with `earendil-works/pi` (everything outside `python/`)

## Daily workflow (Python changes)

```bash
cd ~/Documents/projects/learning/pi-mono/python

# run tests
PYTHONPATH=src python3.11 -m pytest tests/test_pending_ports.py -q

# commit in the monorepo (optional, local history)
cd ..
git add python/
git commit -m "feat(coding-agent): your change"

# publish to the Python GitHub repo
./scripts/push-python-to-github.sh develop "feat(coding-agent): your change"
```

## Stay current with upstream TypeScript

When earendil-works/pi releases updates:

```bash
cd ~/Documents/projects/learning/pi-mono
./scripts/sync-upstream.sh
```

Then port any new TS behavior into `python/` and push again:

```bash
./scripts/push-python-to-github.sh develop "feat: port upstream changes"
```

## Remotes (in pi-mono)

| Remote | Use |
| --- | --- |
| `earendil` | Fetch upstream TS updates (`git fetch earendil`) |
| `py_repo` | Python GitHub repo (`Rudreysh/pi-mono-py`) |
| `my_fork` | Old full fork — **do not use for Python pushes** |

## Install / run Python locally

```bash
cd ~/Documents/projects/learning/pi-mono/python
python3.11 -m pip install -e ".[dev]"
PYTHONPATH=src python3.11 -m pi_mono.coding_agent
```
