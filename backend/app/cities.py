"""Yangon / Mandalay: which city a branch, warehouse or column group belongs to."""
from typing import Literal

City = Literal["YGN", "MDY"]
CITIES: tuple[City, ...] = ("YGN", "MDY")
CITY_NAME: dict[str, str] = {"YGN": "Yangon", "MDY": "Mandalay"}

# The planner's rule: these branches are Mandalay, every other branch is Yangon. Matched without case or spaces,
# so "Nay Pyi Taw" is Naypyitaw.
MANDALAY_BRANCHES = {"mandalay", "taunggyi", "naypyitaw", "subdistributor-upper"}


def _key(value) -> str:
    return "".join(str(value or "").split()).casefold()


def branch_city(branch) -> City:
    """The city a stock or sales branch (or a PDG `WH B` value) belongs to."""
    return "MDY" if _key(branch) in MANDALAY_BRANCHES else "YGN"


def label_city(label) -> City | None:
    """The city a group label names ("YGN IMS", "MDY", "Mandalay"…); None for any other label ("Total IMS")."""
    key = _key(label)
    if "total" in key:
        return None
    if "ygn" in key or "yangon" in key:
        return "YGN"
    if "mdy" in key or "mandalay" in key:
        return "MDY"
    return None


def group_labels(rows_above: list[tuple], width: int) -> list[str | None]:
    """For each column, the nearest text label at or to its left in the rows above a header row (the label sits over
    the first column of its group, like a merged cell). Numbers (column totals) are not labels."""
    labels: list[str | None] = []
    current: str | None = None
    for c in range(width):
        here = next((r[c] for r in rows_above if c < len(r) and isinstance(r[c], str) and r[c].strip()), None)
        if here is not None:
            current = here.strip()
        labels.append(current)
    return labels
