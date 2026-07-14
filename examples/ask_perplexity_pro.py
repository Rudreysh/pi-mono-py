#!/usr/bin/env python3
"""Minimal Perplexity Pro ask script (subscription cookie, no API key).

Usage:
  export PERPLEXITY_SESSION_TOKEN='paste-cookie-value'
  pip install -e '.[perplexity-pro]'   # recommended (curl_cffi)
  python examples/ask_perplexity_pro.py "latest ADHD diagnosis studies"
  python examples/ask_perplexity_pro.py -m sonar "how is ADHD diagnosed"
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from pi_mono.ai.perplexity_pro_client import ask, list_models, validate_session


async def main() -> int:
    parser = argparse.ArgumentParser(description="Ask Perplexity Pro with your subscription cookie")
    parser.add_argument("prompt", nargs="?", help="Question to ask")
    parser.add_argument(
        "-m",
        "--model",
        default="sonnet",
        choices=list_models(),
        help="Pro web model id (default: sonnet)",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only check that PERPLEXITY_SESSION_TOKEN is valid",
    )
    args = parser.parse_args()

    if args.validate_only:
        session = await validate_session()
        user = session.get("user") if isinstance(session, dict) else {}
        email = user.get("email") if isinstance(user, dict) else None
        tier = user.get("subscription_tier") if isinstance(user, dict) else None
        print(f"session ok email={email!r} tier={tier!r}")
        return 0

    if not args.prompt:
        parser.error("prompt is required unless --validate-only")

    result = await ask(args.prompt, model=args.model)
    print(result["text"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
