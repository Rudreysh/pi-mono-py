"""Remote-service error values compatible with the Chord protocol."""

from __future__ import annotations

REMOTE_SERVICE_ERROR_CODES = frozenset(
    {
        "service_not_allowed",
        "service_not_found",
        "service_mode_mismatch",
        "service_member_not_found",
        "service_member_mismatch",
        "service_instance_not_found",
        "service_stale_instance",
        "service_invalid_value",
    }
)


def is_remote_service_error_code(value: object) -> bool:
    return isinstance(value, str) and value in REMOTE_SERVICE_ERROR_CODES


class RemoteServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        if not is_remote_service_error_code(code):
            raise ValueError(f"unknown remote service error code: {code}")
        super().__init__(message)
        self.code = code
