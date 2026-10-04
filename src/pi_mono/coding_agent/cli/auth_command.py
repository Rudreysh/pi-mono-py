"""``pi auth`` commands: print credentials and check provider auth."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from typing import Any, Literal

from pi_mono.ai.models import get_providers
from pi_mono.coding_agent.cli.args import Args, parse_args
from pi_mono.coding_agent.core.model_resolver import resolve_cli_model
from pi_mono.config import APP_NAME
from pi_mono.core.auth_storage import AuthStorage
from pi_mono.core.model_registry import ModelRegistry

AuthCommandKind = Literal["check", "api_key", "bearer_token"]

AUTH_COMMAND_USAGE: dict[AuthCommandKind, str] = {
    "check": f"{APP_NAME} auth check --provider <provider> [--json] [--credentials] [--no-refresh]",
    "api_key": f"{APP_NAME} auth print-api-key --provider <provider> [--model <model>]",
    "bearer_token": (
        f"{APP_NAME} auth print-bearer-token --provider <provider> [--model <model>] "
        "[--min-expiry <duration>]"
    ),
}


class AuthCommandError(Exception):
    pass


@dataclass
class AuthCommand:
    kind: AuthCommandKind
    args: list[str]
    json: bool = False
    credentials: bool = False
    no_refresh: bool = False
    min_expiry_ms: int | None = None


def get_auth_command_name(kind: AuthCommandKind) -> str:
    if kind == "check":
        return "auth check"
    if kind == "api_key":
        return "auth print-api-key"
    return "auth print-bearer-token"


def get_auth_command_usage(kind: AuthCommandKind) -> str:
    return AUTH_COMMAND_USAGE[kind]


def is_auth_command_help(args: list[str]) -> bool:
    return args[:1] == ["auth"] and (
        len(args) < 2 or args[1] == "help" or "--help" in args or "-h" in args
    )


def print_auth_command_help() -> None:
    print(
        """Usage:
  pi auth print-api-key [--provider <provider>] [--model <model>]
  pi auth print-bearer-token [--provider <provider>] [--model <model>] [--min-expiry <duration>]
  pi auth check [--provider <provider>] [--model <model>] [--json] [--credentials] [--no-refresh]

Auth commands require at least one of --provider or --model. Checks refresh expired OAuth credentials by default; --no-refresh prevents this. --credentials emits the credential, or includes it in JSON output."""
    )


def parse_auth_command(args: list[str]) -> AuthCommand | None:
    if not args or args[0] != "auth":
        return None
    kind: AuthCommandKind | None
    if len(args) > 1 and args[1] == "check":
        kind = "check"
    elif len(args) > 1 and args[1] == "print-api-key":
        kind = "api_key"
    elif len(args) > 1 and args[1] == "print-bearer-token":
        kind = "bearer_token"
    else:
        raise AuthCommandError(
            f'Unknown auth command "{args[1] if len(args) > 1 else ""}". '
            f'Use "{APP_NAME} auth print-api-key", "{APP_NAME} auth print-bearer-token", '
            f'or "{APP_NAME} auth check".'
        )

    command_args: list[str] = []
    json_output = False
    credentials = False
    no_refresh = False
    min_expiry_ms: int | None = None
    rest = args[2:]
    index = 0
    while index < len(rest):
        arg = rest[index]
        if arg == "--min-expiry":
            if kind != "bearer_token":
                raise AuthCommandError("--min-expiry is only supported by print-bearer-token")
            index += 1
            value = rest[index] if index < len(rest) else None
            match = re.match(r"^(\d+)(ms|s|m|h)$", value or "", flags=re.IGNORECASE)
            if not match:
                raise AuthCommandError("--min-expiry must use a duration such as 30m or 1h")
            amount = int(match.group(1))
            unit = match.group(2).lower()
            min_expiry_ms = amount * (
                1 if unit == "ms" else 1000 if unit == "s" else 60_000 if unit == "m" else 3_600_000
            )
            index += 1
            continue
        if arg in ("--json", "--credentials", "--no-refresh"):
            if kind != "check":
                raise AuthCommandError(f"{arg} is only supported by auth check")
            if arg == "--json":
                json_output = True
            elif arg == "--credentials":
                credentials = True
            else:
                no_refresh = True
            index += 1
            continue
        command_args.append(arg)
        index += 1

    return AuthCommand(
        kind=kind,
        args=command_args,
        json=json_output,
        credentials=credentials,
        no_refresh=no_refresh,
        min_expiry_ms=min_expiry_ms,
    )


def validate_auth_command_args(parsed: Args, kind: AuthCommandKind) -> dict[str, str | None]:
    provider = (parsed.provider or "").strip() or None
    model = (parsed.model or "").strip() or None
    if parsed.unknown_flags:
        option = next(iter(parsed.unknown_flags))
        raise AuthCommandError(f'Unknown option --{option} for "{get_auth_command_name(kind)}".')
    if parsed.api_key is not None or parsed.messages or parsed.file_args:
        raise AuthCommandError("Auth commands only accept --provider and --model")
    if not provider and not model:
        if kind == "check":
            raise AuthCommandError("Auth checks require --provider <provider> or --model <model>")
        raise AuthCommandError(
            "Credential printing requires --provider <provider> or --model <model>"
        )
    return {"provider": provider, "model": model}


def _get_auth_credential(auth: dict[str, Any] | None) -> str | None:
    if not auth:
        return None
    api_key = auth.get("apiKey")
    if api_key:
        return str(api_key)
    headers = auth.get("headers") or {}
    authorization = next(
        (value for name, value in headers.items() if str(name).lower() == "authorization"),
        None,
    )
    if isinstance(authorization, str):
        match = re.match(r"^Bearer\s+(.+)$", authorization, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _known_provider_ids() -> set[str]:
    return set(get_providers())


def _first_model_for_provider(registry: ModelRegistry, provider: str) -> Any:
    return next((model for model in registry.get_all() if model.get("provider") == provider), None)


def _credential_type(auth_storage: AuthStorage, provider: str) -> str | None:
    cred = auth_storage.data.get(provider)
    if isinstance(cred, dict) and cred.get("type"):
        return str(cred.get("type"))
    if auth_storage.has_auth(provider):
        return "api_key"
    return None


async def _auth_for_provider(registry: ModelRegistry, provider: str, model_id: str | None) -> dict[str, Any]:
    model = None
    if model_id:
        resolved = resolve_cli_model(
            cli_provider=provider, cli_model=model_id, model_registry=registry
        )
        if resolved.error or resolved.model is None:
            raise AuthCommandError(resolved.error or "Unable to resolve the requested provider/model")
        model = resolved.model
    else:
        model = _first_model_for_provider(registry, provider)
        if model is None:
            raise AuthCommandError(
                f'Unknown provider "{provider}". Use --list-models to see available providers.'
            )
    return await registry.get_api_key_and_headers(model)


async def run_auth_command(args: list[str]) -> bool:
    if is_auth_command_help(args):
        print_auth_command_help()
        return True

    try:
        command = parse_auth_command(args)
    except AuthCommandError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    if command is None:
        return False

    parsed = parse_args(command.args)
    if parsed.unknown_flags:
        option = next(iter(parsed.unknown_flags))
        print(
            f'Error: Unknown option --{option} for "{get_auth_command_name(command.kind)}".',
            file=sys.stderr,
        )
        print(
            f'Use "{APP_NAME} --help" or "{get_auth_command_usage(command.kind)}".',
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        if parsed.diagnostics:
            raise AuthCommandError("\n".join(item["message"] for item in parsed.diagnostics))

        auth_storage = AuthStorage.create()
        registry = ModelRegistry.create(auth_storage)

        if command.kind != "check":
            credential = await _print_credential(parsed, registry, auth_storage, command.kind)
            sys.stdout.write(f"{credential}\n")
            return True

        requested = validate_auth_command_args(parsed, command.kind)
        provider = requested["provider"]
        if requested["model"]:
            resolved = resolve_cli_model(
                cli_provider=provider, cli_model=requested["model"], model_registry=registry
            )
            if resolved.error or resolved.model is None:
                raise AuthCommandError(resolved.error or f'Unable to resolve model "{requested["model"]}"')
            provider = str(resolved.model.get("provider"))
        if not provider:
            raise AuthCommandError("Unable to resolve an auth provider")

        result = await _check_provider_auth(provider, auth_storage, registry)
        credential: str | None = None
        if command.credentials and result["status"] == "ready":
            credential = _get_auth_credential(
                await _auth_for_provider(registry, provider, requested["model"])
            )
            if not credential:
                result = {
                    "status": "not_ready",
                    "provider": provider,
                    "reason": "credential_not_available",
                }
        output: Any = {**result, **({"credentials": credential} if credential else {})}
        if command.json:
            sys.stdout.write(f"{json.dumps(output)}\n")
        else:
            sys.stdout.write(f"{credential or result['status']}\n")
        raise SystemExit(0 if result["status"] == "ready" else 1 if result["status"] == "not_ready" else 2)
    except AuthCommandError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(2 if command.kind == "check" else 1) from error
    except SystemExit:
        raise
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(2 if command.kind == "check" else 1) from error


async def _print_credential(
    parsed: Args,
    registry: ModelRegistry,
    auth_storage: AuthStorage,
    kind: AuthCommandKind,
) -> str:
    requested = validate_auth_command_args(parsed, kind)
    provider = requested["provider"]
    if requested["model"] and not provider:
        resolved = resolve_cli_model(cli_model=requested["model"], model_registry=registry)
        if resolved.model is None:
            raise AuthCommandError(
                f'Model "{requested["model"]}" not found. Use --list-models to see available models.'
            )
        provider = str(resolved.model.get("provider"))
    if not provider:
        raise AuthCommandError("Unable to resolve an auth provider")

    cred_type = _credential_type(auth_storage, provider)
    if kind == "api_key" and cred_type == "oauth":
        raise AuthCommandError(f'Provider "{provider}" is configured with OAuth, not an API key')
    if kind == "bearer_token" and cred_type != "oauth":
        raise AuthCommandError(f'Provider "{provider}" is not configured with an OAuth bearer token')

    auth = await _auth_for_provider(registry, provider, requested["model"])
    value = _get_auth_credential(auth if auth.get("ok") else None)
    if not value:
        label = "API key" if kind == "api_key" else "OAuth bearer token"
        raise AuthCommandError(f"No usable {label} is configured")
    return value


async def _check_provider_auth(
    provider: str, auth_storage: AuthStorage, registry: ModelRegistry
) -> dict[str, Any]:
    if provider not in _known_provider_ids() and not any(
        model.get("provider") == provider for model in registry.get_all()
    ):
        return {"status": "not_ready", "provider": provider, "reason": "provider_not_found"}
    try:
        if not auth_storage.has_auth(provider):
            return {
                "status": "not_ready",
                "provider": provider,
                "reason": "credentials_not_configured",
            }
        auth = await _auth_for_provider(registry, provider, None)
        if not auth.get("ok"):
            return {
                "status": "not_ready",
                "provider": provider,
                "reason": "credentials_not_configured",
            }
        cred_type = _credential_type(auth_storage, provider)
        return {
            "status": "ready",
            "provider": provider,
            "authType": "oauth" if cred_type == "oauth" else "api_key",
        }
    except AuthCommandError:
        return {"status": "not_ready", "provider": provider, "reason": "provider_not_found"}
    except Exception:
        return {"status": "invalid", "provider": provider, "reason": "invalid_state"}
