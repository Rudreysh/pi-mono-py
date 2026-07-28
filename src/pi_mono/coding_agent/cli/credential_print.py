"""``pi auth print-api-key`` -- print the resolved API key for a provider.

Useful for scripting and debugging: resolves the API key the same way the
agent runtime would (env vars, OAuth store, ADC chain) and prints it to stdout.
"""

from __future__ import annotations

import sys
from typing import Any

from pi_mono.ai.env_api_keys import get_env_api_key


def run_credential_print(provider: str, *, env: dict[str, str] | None = None) -> None:
    """Print the API key for *provider* to stdout, or exit 1 with a message on stderr."""
    key = get_env_api_key(provider, env)
    if key is None:
        print(f"No API key found for provider: {provider}", file=sys.stderr)
        raise SystemExit(1)
    print(key)


def add_credential_print_subcommand(subparsers: Any) -> None:
    """Wire ``print-api-key`` into an argparse subparser group (e.g. ``pi auth``)."""
    parser = subparsers.add_parser(
        "print-api-key",
        help="Print the resolved API key for a provider",
    )
    parser.add_argument("provider", help="Provider id (e.g. openai, anthropic)")
    parser.set_defaults(func=lambda args: run_credential_print(args.provider))
