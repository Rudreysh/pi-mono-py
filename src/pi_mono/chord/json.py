"""Strict JSON validation used at Chord service boundaries."""

from __future__ import annotations

import math
from typing import Any


def is_json_value(value: object) -> bool:
    """Return whether ``value`` is finite JSON composed of lists and dicts.

    A bounded ancestor walk rejects circular structures before they can reach a
    serializer or a replicated-state delta.
    """

    return _check(value, set(), 0)


def _check(value: object, ancestors: set[int], depth: int) -> bool:
    if depth > 512:
        return False
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return math.isfinite(value)
    if not isinstance(value, (list, dict)):
        return False
    identity = id(value)
    if identity in ancestors:
        return False
    ancestors.add(identity)
    try:
        if isinstance(value, list):
            return all(_check(item, ancestors, depth + 1) for item in value)
        if type(value) is not dict or not all(isinstance(key, str) for key in value):
            return False
        return all(_check(item, ancestors, depth + 1) for item in value.values())
    finally:
        ancestors.remove(identity)
