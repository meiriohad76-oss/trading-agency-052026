from __future__ import annotations

from datetime import datetime


def parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("datetime values must be strings")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return parse_datetime(value)


def parse_int(value: object) -> int:
    if isinstance(value, bool):
        raise TypeError("integer values cannot be booleans")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise TypeError("integer values must be strings or integers")


def parse_float(value: object) -> float:
    if isinstance(value, bool):
        raise TypeError("float values cannot be booleans")
    if isinstance(value, int | float | str):
        return float(value)
    raise TypeError("float values must be strings or numbers")


def optional_float(value: object) -> float | None:
    if value is None:
        return None
    return parse_float(value)
