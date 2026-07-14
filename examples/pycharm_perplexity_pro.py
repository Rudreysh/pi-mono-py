#!/usr/bin/env python3
"""PyCharm one-click Perplexity Pro ask (subscription cookie, NO API key).

1. Get a FRESH cookie (old ones expire / invalidate after logout):
   - Open https://www.perplexity.ai and make sure you are logged into Pro
   - Chrome: F12 → Application → Cookies → https://www.perplexity.ai
   - Click cookie named exactly: __Secure-next-auth.session-token
   - Copy the Value only (long eyJ... string). Do NOT copy the cookie name.
2. Paste it into SESSION_TOKEN below (between the quotes).
3. Run this file in PyCharm.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# =============================================================================
# HARDCODE THESE — then just press Run in PyCharm
# =============================================================================

# Paste ONLY the cookie VALUE (starts with eyJ...). Replace this whole string.
SESSION_TOKEN = "PASTE_YOUR___Secure-next-auth.session-token_VALUE_HERE"

PROMPT = "how is ADHD diagnosed"

MODEL = "sonar"  # auto | sonar | sonnet | gpt | gpt-5.4 | gpt-mini | gemini | ...

PI_MONO_SRC = Path("/Users/rukesh/Documents/projects/learning/pi-mono/python/src")

# =============================================================================

if str(PI_MONO_SRC) not in sys.path:
    sys.path.insert(0, str(PI_MONO_SRC))


async def main() -> None:
    from pi_mono.ai.utils.oauth.perplexity_pro import normalize_session_token
    from pi_mono.ai.perplexity_pro_client import ask, validate_session

    if not SESSION_TOKEN or SESSION_TOKEN.startswith("PASTE_YOUR_"):
        raise SystemExit(
            "Edit SESSION_TOKEN in this file: paste a FRESH cookie value, save, Run again."
        )

    token = normalize_session_token(SESSION_TOKEN)
    print(f"token length: {len(token)}")
    print(f"token starts: {token[:20]}...")
    print(f"token ends:   ...{token[-12:]}")
    if not token.startswith("eyJ"):
        print(
            "WARNING: token usually starts with eyJ. You may have pasted the wrong cookie "
            "or included extra text."
        )

    print("\nValidating Perplexity Pro session…")
    try:
        session = await validate_session(token)
    except RuntimeError as error:
        raise SystemExit(
            f"{error}\n\n"
            "Fix:\n"
            "1) Open https://www.perplexity.ai and log in (Pro).\n"
            "2) F12 → Application → Cookies → www.perplexity.ai\n"
            "3) Copy VALUE of __Secure-next-auth.session-token only\n"
            "4) Paste into SESSION_TOKEN in this file, Save, Run again\n"
            "Do not paste the cookie into chat."
        ) from error

    user = session.get("user") if isinstance(session, dict) else {}
    print(
        "OK —",
        (user or {}).get("email"),
        "| tier:",
        (user or {}).get("subscription_tier"),
    )
    print(f"\nAsking ({MODEL}): {PROMPT}\n")

    result = await ask(PROMPT, model=MODEL, session_token=token)
    print("=== answer ===\n")
    print(result["text"])


if __name__ == "__main__":
    asyncio.run(main())
