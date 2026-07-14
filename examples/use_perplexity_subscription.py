#!/usr/bin/env python3
"""Use Perplexity Pro subscription from a normal Python file (NO API key).

Setup (once):
  1. Browser → https://www.perplexity.ai (logged into Pro)
  2. DevTools → Application → Cookies → copy __Secure-next-auth.session-token
  3. Put that value in PERPLEXITY_SESSION_TOKEN below (or as an env var)

Run:
  /path/to/paddle_ocr/bin/python this_file.py
"""

from __future__ import annotations

import asyncio
import os

# --- paste cookie here OR set env PERPLEXITY_SESSION_TOKEN ---
SESSION_TOKEN = os.environ.get("PERPLEXITY_SESSION_TOKEN", "").strip()
# SESSION_TOKEN = "eyJ..."  # uncomment and paste if you prefer hardcoding (don't commit)

MODEL = "sonar"  # sonnet | sonar | gpt | auto | gemini | ...
PROMPT = "how is ADHD diagnosed"


async def main() -> None:
    # Import after path/install is ready
    from pi_mono.ai.perplexity_pro_client import ask, list_models, validate_session

    if not SESSION_TOKEN:
        raise SystemExit(
            "Set PERPLEXITY_SESSION_TOKEN env var, or paste SESSION_TOKEN in this file.\n"
            "Models: " + ", ".join(list_models())
        )

    session = await validate_session(SESSION_TOKEN)
    user = session.get("user") if isinstance(session, dict) else {}
    print(
        "logged in:",
        (user or {}).get("email"),
        "tier:",
        (user or {}).get("subscription_tier"),
    )

    result = await ask(PROMPT, model=MODEL, session_token=SESSION_TOKEN)
    print("\n=== answer ===\n")
    print(result["text"])


if __name__ == "__main__":
    asyncio.run(main())
