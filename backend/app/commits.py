"""Commits: stock already agreed with a principal but not yet in the Stock in Transit file, entered by hand on the New
plan page. Each one is added to its SKU's stock in transit, in its region and week, exactly like a file delivery."""
from datetime import date, timedelta

from app.cities import CITIES
from app.models import CityInput, Commit, ParsedInput, SitArrival

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _day_text(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def _check(i: int, commit: Commit, codes: set[str], plan_week: date) -> None:
    where = f"Commit {i}: "
    if commit.sap_code not in codes:
        raise ValueError(f"{where}SAP code '{commit.sap_code}' is not in the Sales Forecast file.")
    if not commit.cartons > 0:
        raise ValueError(f"{where}cartons must be a number above 0.")
    if commit.region not in CITIES:
        raise ValueError(f"{where}region must be Yangon or Mandalay.")
    if commit.arrival_week.weekday() != 0:
        raise ValueError(f"{where}the arrival week must be given by its Monday.")
    if commit.arrival_week < plan_week:
        raise ValueError(f"{where}the arrival week is before the plan week ({_day_text(plan_week)}).")


def apply_commits(parsed: ParsedInput, commits: list[Commit], plan_date: date) -> ParsedInput:
    """A copy of parsed with each commit added to its SKU's stock in transit (the SKU total and its region), arriving
    on the Monday of its week, and the commits recorded. Raises ValueError naming the first bad commit (1-based)."""
    if not commits:
        return parsed
    plan_week = plan_date - timedelta(days=plan_date.weekday())
    codes = {s.sap_code for s in parsed.skus}
    for i, commit in enumerate(commits, start=1):
        _check(i, commit, codes, plan_week)

    skus = []
    for sku in parsed.skus:
        mine = [c for c in commits if c.sap_code == sku.sap_code]
        if not mine:
            skus.append(sku)
            continue
        arrivals = [SitArrival(date=c.arrival_week, cartons=c.cartons, source="commit") for c in mine]
        # A run saved before the Stock in Transit file has no arrivals: its SIT counts from the plan date, so keep
        # that as an arrival on the plan date before adding the commits.
        existing = (sku.sit_arrivals if sku.sit_arrivals is not None
                    else [SitArrival(date=plan_date, cartons=sku.sit)] if sku.sit else [])
        update = {"sit": sku.sit + sum(c.cartons for c in mine),
                  "sit_arrivals": sorted([*existing, *arrivals], key=lambda a: a.date)}
        if sku.cities is not None:
            cities = dict(sku.cities)
            for region in CITIES:
                theirs = [a for c, a in zip(mine, arrivals) if c.region == region]
                if theirs:
                    base = cities.get(region) or CityInput()
                    cities[region] = base.model_copy(update={
                        "sit": base.sit + sum(a.cartons for a in theirs),
                        "sit_arrivals": sorted([*base.sit_arrivals, *theirs], key=lambda a: a.date)})
            update["cities"] = cities
        skus.append(sku.model_copy(update=update))
    return parsed.model_copy(update={"skus": skus, "commits": list(commits)})


def remove_commits(parsed: ParsedInput) -> ParsedInput:
    """A copy of parsed without its commits: every commit arrival taken off its SKU (and region), and the SIT totals
    back to the Stock in Transit file's. The inverse of apply_commits, used to replace a saved plan's commits."""
    if not parsed.commits and not any(a.source == "commit" for s in parsed.skus for a in (s.sit_arrivals or [])):
        return parsed

    def without(arrivals: list[SitArrival]) -> tuple[list[SitArrival], float]:
        kept = [a for a in arrivals if a.source != "commit"]
        return kept, sum(a.cartons for a in arrivals if a.source == "commit")

    skus = []
    for sku in parsed.skus:
        if not any(a.source == "commit" for a in (sku.sit_arrivals or [])):
            skus.append(sku)
            continue
        kept, removed = without(sku.sit_arrivals)
        update = {"sit_arrivals": kept, "sit": sku.sit - removed}
        if sku.cities is not None:
            cities = {}
            for region, c in sku.cities.items():
                c_kept, c_removed = without(c.sit_arrivals)
                cities[region] = c.model_copy(update={"sit_arrivals": c_kept, "sit": c.sit - c_removed})
            update["cities"] = cities
        skus.append(sku.model_copy(update=update))
    return parsed.model_copy(update={"skus": skus, "commits": []})
