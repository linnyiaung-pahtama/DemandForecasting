"""Helpers for "YYYY-MM" month keys."""
from datetime import date


def _index(key: str) -> int:
    year, month = key.split("-")
    return int(year) * 12 + int(month) - 1


def _key(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def prev_months(key: str, n: int) -> list[str]:
    """The n months before `key`, oldest first."""
    base = _index(key)
    return [_key(base - n + i) for i in range(n)]


def next_months(key: str, n: int) -> list[str]:
    """`key` and the following n-1 months."""
    base = _index(key)
    return [_key(base + i) for i in range(n)]


def month_label(key: str) -> str:
    """"2026-07" -> "Jul 2026"."""
    year, month = key.split("-")
    return f"{date(int(year), int(month), 1):%b} {year}"
