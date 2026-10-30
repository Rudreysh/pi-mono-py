# pi-mono-python

Python port of [pi-mono](https://github.com/badlogic/pi-mono) — the pi agent harness monorepo (coding agent CLI, agent runtime, and multi-provider LLM API).

This repository contains only the Python implementation. The original TypeScript packages live in the upstream monorepo.

## Requirements

- Python 3.11+

## Install

```bash
python3.11 -m pip install -e ".[dev]"
```

## Usage

Interactive coding agent (equivalent to the `pi` CLI):

```bash
python3.11 -m pi_mono.coding_agent
```

Print mode:

```bash
python3.11 -m pi_mono.coding_agent -p "Say exactly: ok"
```

After install, the `pi` and `pi-ai` console scripts are also available.

## Packages

| Module | Description |
|--------|-------------|
| `pi_mono.ai` | Multi-provider LLM API (OpenAI, Anthropic, Google, Mistral, Bedrock, …) |
| `pi_mono.agent` | Agent runtime with tool calling and harness |
| `pi_mono.coding_agent` | Interactive coding agent CLI |
| `pi_mono.core` | Shared core utilities |
| `pi_mono.tui` | Terminal UI components |

## Development Layout

This checkout is the authoritative Python source. Develop and push Python
directly here on `develop`. The sibling `../pi-mono` checkout contains the
original TypeScript source on `main` and personal TypeScript work on
`ts-custom`. See [the maintenance workflow](docs/workflow.md).

Use the local development environment:

```bash
source .venv/bin/activate
python -m pi_mono.coding_agent
python -m pytest tests/test_standalone_layout.py
```

Catalog scripts accept `--typescript-root ../pi-mono` or `PI_MONO_ROOT` when
the TypeScript checkout is elsewhere. The optional TypeScript extension bridge
uses that same environment variable and the TypeScript checkout's Node dependencies.

## Tests

```bash
cd /path/to/pi-mono-python
python3.11 -m pytest
```

## Upstream

- Original project: [badlogic/pi-mono](https://github.com/badlogic/pi-mono)
- TypeScript fork: [Rudreysh/pi-mono](https://github.com/Rudreysh/pi-mono) (`main` mirrors upstream; `ts-custom` holds personal features)
- Python development: [Rudreysh/pi-mono-py](https://github.com/Rudreysh/pi-mono-py) (`develop`)

## License

Same as upstream pi-mono — see [LICENSE](LICENSE).
