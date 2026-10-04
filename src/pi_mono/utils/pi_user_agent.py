import sys
import platform


def get_pi_user_agent(version: str | None = None) -> str:
    """Generate a custom User-Agent string for HTTP requests.

    With a version this is used by version-check. Without a version it matches
    the TypeScript AI provider default: ``pi (platform release; arch)``.
    """
    arch = platform.machine().lower()
    if arch == "x86_64":
        arch = "x64"
    elif arch == "aarch64":
        arch = "arm64"

    if version:
        runtime = f"python/{platform.python_version()}"
        return f"pi/{version} ({sys.platform}; {runtime}; {arch})"
    return f"pi ({sys.platform} {platform.release()}; {arch})"
