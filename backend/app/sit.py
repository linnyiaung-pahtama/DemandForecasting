"""The Stock in Transit file: SIT per SKU by arrival week ("<Month> W<n> Arrival" columns), as dated arrivals."""
import re
from collections import defaultdict
from datetime import date, timedelta
from io import BytesIO

from openpyxl import load_workbook

from app.cities import CITIES, group_labels, label_city
from app.models import (CityInput, InputFileError, ParsedInput, ParseWarning, SitArrival, SitFileSummary, SitLine,
                        SitReport)
from app.parsing import HEADER_SEARCH_ROWS, _collapse, _month_number, _norm, _to_number
from app.stock import _code

SIT_NAME = "Stock in Transit file"

ARRIVAL_RE = re.compile(r"^([a-z]+)\s*w\s*([1-5])\s*arrival$")

MISSING_SHEET = ("No sheet has a SAP Code column and '<Month> W<n> Arrival' columns "
                 "(looked in the first 10 rows of each sheet).")


def _arrival(header) -> tuple[int, int] | None:
    """(month, week) for an arrival header such as "Oct W3 Arrival"; None for any other header."""
    m = ARRIVAL_RE.match(_norm(header))
    if not m:
        return None
    month = _month_number(m.group(1))
    return None if month is None else (month, int(m.group(2)))


def _find_header(rows: list[tuple]) -> tuple[int, int, dict[int, tuple[int, int]]] | None:
    """(header row index, SAP Code column, column -> (month, week)) of the first row with both."""
    for i, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        sap = next((c for c, h in enumerate(row) if _norm(h) == "sap code"), None)
        arrivals = {c: a for c, h in enumerate(row) if (a := _arrival(h)) is not None}
        if sap is not None and arrivals:
            return i, sap, arrivals
    return None


def parse_sit(data: bytes) -> SitReport:
    """Arrival lines from the first sheet with a SAP Code header and arrival columns. Blank and 0 cells are no
    arrival; negative or non-numeric cells are skipped with a warning."""
    try:
        wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise InputFileError("Could not read the file as an Excel .xlsx workbook.") from None
    found = None
    try:
        for ws in wb.worksheets:
            ws.reset_dimensions()  # read-only mode trusts the stored sheet size, which exports sometimes get wrong
            rows = list(ws.iter_rows(values_only=True))
            header = _find_header(rows)
            if header is not None:
                found = rows, header
                break
    finally:
        wb.close()
    if found is None:
        raise InputFileError(MISSING_SHEET)
    rows, (header_idx, c_sap, arrival_cols) = found
    header_text = {c: _collapse(rows[header_idx][c]) for c in arrival_cols}
    # Each arrival column's city from the YGN / MDY label above it; no label means Yangon.
    labels = group_labels(rows[:header_idx], len(rows[header_idx]))
    col_city = {c: (label_city(labels[c]) if labels[c] else None) or "YGN" for c in arrival_cols}

    totals: dict[tuple[str, int, int, str], float] = defaultdict(float)
    codes: dict[str, None] = {}
    warnings: list[ParseWarning] = []
    for row in rows[header_idx + 1:]:
        raw = row[c_sap] if c_sap < len(row) else None
        if raw is None or _collapse(raw) == "":
            continue
        code = _code(raw)
        codes[code] = None
        for c, (month, week) in arrival_cols.items():
            v = row[c] if c < len(row) else None
            if v is None or (isinstance(v, str) and v.strip() == ""):
                continue
            n = _to_number(v)
            if n is None or n < 0:
                warnings.append(ParseWarning(sap_code=code, column=header_text[c],
                                             message="not a number of cartons above 0; skipped"))
            elif n > 0:
                totals[(code, month, week, col_city[c])] += n
    # One line per SKU, arrival label and city; apply_sit adds the cities together for the SKU's total.
    lines = [SitLine(code=code, month=month, week=week, cartons=cartons, city=city)
             for (code, month, week, city), cartons in totals.items()]
    return SitReport(lines=lines, codes=list(codes), warnings=warnings)


def _month_index(year: int, month: int) -> int:
    return year * 12 + month - 1


def week_monday(month: int, week: int, mtd_month: str) -> date:
    """The Monday a "<month> W<week>" delivery lands on. Weeks run Monday to Sunday and W1 is the week holding the
    1st, so the last week of a month and W1 of the next are the same week unless the 1st is a Monday. The year is
    the one putting the month nearest the MTD month (a tie, 6 months either way, goes to the later year)."""
    mtd_year, mtd_mon = int(mtd_month[:4]), int(mtd_month[5:])
    target = _month_index(mtd_year, mtd_mon)
    year = min((mtd_year + 1, mtd_year, mtd_year - 1),
               key=lambda y: abs(_month_index(y, month) - target))  # later years first, so a tie takes the later
    first = date(year, month, 1)
    return first - timedelta(days=first.weekday()) + timedelta(weeks=week - 1)


def _day_month(d: date) -> str:
    return f"{d.day} {date(2000, d.month, 1).strftime('%b')}"  # e.g. "17 Oct"


def run_out_message(runs_out_on: date, arrival: date) -> str:
    """The run-out flag's text, e.g. "runs out about 17 Oct, before its stock in transit arrives on 19 Oct"."""
    return f"runs out about {_day_month(runs_out_on)}, before its stock in transit arrives on {_day_month(arrival)}"


def apply_sit(parsed: ParsedInput, report: SitReport) -> tuple[ParsedInput, SitFileSummary, list[ParseWarning]]:
    """A copy of parsed whose SKUs carry their arrivals (sorted, same dates added) and SIT total, the file summary,
    and the file's warnings followed by the merge warnings."""
    data_codes = {s.sap_code for s in parsed.skus}
    by_code: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    by_city: dict[str, dict[str, dict[date, float]]] = {c: defaultdict(lambda: defaultdict(float)) for c in CITIES}
    in_file = set(report.codes) | {line.code for line in report.lines}
    for line in report.lines:
        day = week_monday(line.month, line.week, parsed.mtd_month)
        by_code[line.code][day] += line.cartons
        by_city[line.city if line.city in by_city else "YGN"][line.code][day] += line.cartons

    def arrivals_of(days: dict[date, float]) -> list[SitArrival]:
        return [SitArrival(date=d, cartons=c) for d, c in sorted(days.items())]

    skus = []
    for sku in parsed.skus:
        arrivals = arrivals_of(by_code.get(sku.sap_code, {}))
        update = {"sit_arrivals": arrivals, "sit": sum(a.cartons for a in arrivals)}
        if sku.cities is not None:
            cities = {}
            for city in CITIES:
                city_arrivals = arrivals_of(by_city[city].get(sku.sap_code, {}))
                cities[city] = (sku.cities.get(city) or CityInput()).model_copy(update={
                    "sit_arrivals": city_arrivals, "sit": sum(a.cartons for a in city_arrivals)})
            update["cities"] = cities
        skus.append(sku.model_copy(update=update))

    warnings = [w for w in report.warnings if w.sap_code in data_codes]
    not_in_data = in_file - data_codes
    if not_in_data:
        warnings.append(ParseWarning(sap_code=None, column=None, message=(
            f"{len(not_in_data)} stock codes in the {SIT_NAME} are not in the Sales Forecast file; ignored")))
    missing = data_codes - in_file
    if missing:
        warnings.append(ParseWarning(sap_code=None, column=None, message=(
            f"{len(missing)} SKUs in the Sales Forecast file are not in the {SIT_NAME}; their SIT is 0")))

    with_sit = [s for s in skus if s.sit > 0]
    dates = [a.date for s in with_sit for a in s.sit_arrivals]
    summary = SitFileSummary(skus_with_sit=len(with_sit), cartons=sum(s.sit for s in with_sit),
                             first_arrival=min(dates, default=None), last_arrival=max(dates, default=None))
    return parsed.model_copy(update={"skus": skus}), summary, warnings
