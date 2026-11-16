import math
import re
from datetime import date, timedelta
from io import BytesIO

from openpyxl import load_workbook

from app.cities import CITY_NAME, group_labels, label_city
from app.models import CityInput, InputFileError, ParsedInput, ParseWarning, SkuInput
from app.months import month_label, next_months

REQUIRED_COLUMNS = [
    "SAP Code",
    "By Principal",
    "Description",
    "Packing Size",  # or "UOM" (PACKING_SIZE_NAMES)
    "Shelf Life month",
]

# The packing size column's accepted headers; newer files call it "UOM".
PACKING_SIZE_NAMES = ["Packing Size", "UOM"]

# Stock now comes from the PDG Stock List and PG Expiry Check files, and stock in transit from the Stock in Transit
# file; these Data columns are never read.
STOCK_COLUMNS = ["Sellable (PG)", "Sellable (PDG)", "Total Sellable (Ctns)",
                 "Non-Sellable (PG)", "Non-Sellable (PDG)", "Total Non-Sellable (Ctns)", "SIT Ctns (pending order)"]

# MOQ and lead time are supplier settings now; these Data columns are never read.
SUPPLIER_SETTING_COLUMNS = ["MOQ", "Lead Time"]

MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august",
               "september", "october", "november", "december"]

MTD_RE = re.compile(r"^([a-z]+)'(\d{2}) mtd sale \((\d{1,2})-(\d{1,2}) ([a-z]+)\)$")
FORECAST_RE = re.compile(r"^(\d{4}) ([a-z]+) ims$")
HEADER_SEARCH_ROWS = 10


def _collapse(value) -> str:
    return re.sub(r"\s+", " ", str(value)).strip() if value is not None else ""


def _norm(value) -> str:
    # curly apostrophes (as typed by Excel autocorrect) are matched as plain ones
    return _collapse(value).replace("’", "'").replace("‘", "'").casefold()


def _month_number(word: str) -> int | None:
    """1-12 for a month name or abbreviation of at least 3 letters (Oct, Sept, June, September)."""
    if len(word) < 3:
        return None
    for i, name in enumerate(MONTH_NAMES, start=1):
        if name.startswith(word):
            return i
    return None


def _next_month(key: str) -> str:
    year, mon = int(key[:4]), int(key[5:])
    return f"{year + (mon == 12):04d}-{mon % 12 + 1:02d}"


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _to_number(v) -> float | None:
    """A float for numbers and numeric text (e.g. " 1,250.5 "); None if not numeric."""
    if _is_number(v):
        return float(v)
    if isinstance(v, str):
        try:
            n = float(v.strip().replace(",", ""))
        except ValueError:
            return None
        return n if math.isfinite(n) else None
    return None


def find_header_row(rows: list[tuple], required: list[str]) -> tuple[int, dict[str, int]] | None:
    """(row index, normalized header -> column index) of the first header row with all required columns."""
    for i, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        columns: dict[str, int] = {}
        for c, h in enumerate(row):
            if _norm(h):
                columns.setdefault(_norm(h), c)
        if all(_norm(name) in columns for name in required):
            return i, columns
    return None


def parse_input(data: bytes) -> ParsedInput:
    try:
        wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise InputFileError("Could not read the file as an Excel .xlsx workbook.") from None
    try:
        if "Data" not in wb.sheetnames:
            raise InputFileError("The workbook has no 'Data' sheet.")
        rows = list(wb["Data"].iter_rows(values_only=True))
    finally:
        wb.close()

    header_idx = next(
        (i for i, row in enumerate(rows[:HEADER_SEARCH_ROWS]) if any(_norm(c) == "sap code" for c in row)),
        None,
    )
    if header_idx is None:
        raise InputFileError("Could not find a header row containing 'SAP Code' in the 'Data' sheet.")
    header = rows[header_idx]

    # normalized header -> (column index, header text as in the file with whitespace collapsed)
    columns: dict[str, tuple[int, str]] = {}
    for i, h in enumerate(header):
        if _norm(h):
            columns.setdefault(_norm(h), (i, _collapse(h)))

    packing_key = next((_norm(n) for n in PACKING_SIZE_NAMES if _norm(n) in columns), None)
    missing = [name for name in REQUIRED_COLUMNS if name != "Packing Size" and _norm(name) not in columns]
    if packing_key is None:
        missing.insert(REQUIRED_COLUMNS.index("Packing Size"), "Packing Size (or UOM)")
    if missing:
        raise InputFileError("The 'Data' sheet is missing required column(s): " + ", ".join(missing) + ".")

    warnings: list[ParseWarning] = []
    if any(_norm(name) in columns for name in STOCK_COLUMNS):
        warnings.append(ParseWarning(
            sap_code=None, column=None,
            message="Stock and SIT columns in the Data sheet are ignored; stock comes from the PDG Stock List "
                    "and PG Expiry Check files, and stock in transit from the Stock in Transit file."))
    if any(_norm(name) in columns for name in SUPPLIER_SETTING_COLUMNS):
        warnings.append(ParseWarning(
            sap_code=None, column=None,
            message="MOQ and Lead Time columns in the Data sheet are ignored; they come from Principal settings."))

    mtd_cols = [(n, c) for n, c in columns.items() if MTD_RE.match(n)]
    if len(mtd_cols) != 1:
        raise InputFileError(
            "Expected exactly one MTD sales column (e.g. \"Oct'26 MTD Sale (1-11 Oct)\"), "
            f"found {len(mtd_cols)}."
        )
    mtd_norm, (mtd_col, mtd_label) = mtd_cols[0]
    m = MTD_RE.match(mtd_norm)
    mtd_mon = _month_number(m.group(1))
    if mtd_mon is None:
        raise InputFileError(f"Unrecognised month in MTD column header: {mtd_label}.")
    try:
        mtd_end = date(2000 + int(m.group(2)), mtd_mon, int(m.group(4)))
    except ValueError:
        raise InputFileError(f"Invalid date in MTD column header: {mtd_label}.") from None
    mtd_month = f"{mtd_end.year:04d}-{mtd_end.month:02d}"

    forecast_cols: list[tuple[str, int, str]] = []  # (YYYY-MM, column index, header text)
    for n, (i, text) in columns.items():
        fm = FORECAST_RE.match(n)
        if not fm:
            # the city forecast block's own total columns ("YGN IMS Total", "Total IMS") are not forecast months
            if "ims" in n and not n.endswith("ims total") and n != "total ims":
                warnings.append(ParseWarning(
                    sap_code=None, column=text,
                    message="header looks like a forecast column but does not match the expected "
                            "pattern (e.g. '2026 Oct IMS'); column ignored"))
            continue
        mon = _month_number(fm.group(2))
        if mon is None:
            raise InputFileError(f"Unrecognised month in forecast column header: {text}.")
        forecast_cols.append((f"{int(fm.group(1)):04d}-{mon:02d}", i, text))

    city_cols = _city_forecast_columns(rows[:header_idx], header)
    if len(city_cols) == 1:
        have = next(iter(city_cols))
        other = "MDY" if have == "YGN" else "YGN"
        raise InputFileError(
            f"The 'Data' sheet has {CITY_NAME[have]} forecast columns but no {CITY_NAME[other]} forecast columns "
            f"(headers like \"Oct'26\" under a '{other} IMS' label).")
    if not forecast_cols and not city_cols:
        raise InputFileError("No forecast columns found (expected headers like '2026 Oct IMS').")

    window = next_months(mtd_month, 3)  # the forecast months the order calculation uses
    if forecast_cols:
        _check_forecast_months(forecast_cols, mtd_month, window, "", warnings)
    for city, cols in city_cols.items():
        _check_forecast_months(cols, mtd_month, window, CITY_NAME[city] + " ", warnings)

    def col(name: str) -> tuple[int, str]:
        return columns[_norm(name)]

    c_sap, _ = col("SAP Code")
    c_sup, _ = col("By Principal")
    c_desc, _ = col("Description")
    c_pack, h_pack = columns[packing_key]
    c_shelf, _ = col("Shelf Life month")

    skus: list[SkuInput] = []
    seen: set[str] = set()

    for row in rows[header_idx + 1:]:
        def cell(i: int):
            return row[i] if i < len(row) else None

        raw_sap = cell(c_sap)
        if raw_sap is None or _collapse(raw_sap) == "":
            continue
        sap = str(int(raw_sap)) if _is_number(raw_sap) else str(raw_sap).strip()

        if sap in seen:
            warnings.append(ParseWarning(sap_code=sap, column=None,
                                         message="duplicate SAP Code; later row ignored"))
            continue
        seen.add(sap)

        def num(i: int, header: str) -> float:
            v = _to_number(cell(i))
            if v is not None:
                return v
            warnings.append(ParseWarning(sap_code=sap, column=header,
                                         message="empty or non-numeric value treated as 0"))
            return 0.0

        packing = _to_number(cell(c_pack))
        if packing is None:
            warnings.append(ParseWarning(sap_code=sap, column=h_pack,
                                         message="empty or non-numeric packing size treated as unknown"))

        # Shelf life and the MTD quantity are not used in the calculation, so their odd values are not warned about.
        shelf_num = _to_number(cell(c_shelf))
        shelf = shelf_num if shelf_num is not None and shelf_num > 0 else None
        mtd = _to_number(cell(mtd_col)) or 0.0

        def read_forecast(cols: list[tuple[str, int, str]]) -> dict[str, float]:
            out: dict[str, float] = {}
            for key, i, text in cols:
                fc = num(i, text)
                if fc < 0:
                    warnings.append(ParseWarning(sap_code=sap, column=text,
                                                 message="negative forecast treated as 0"))
                    fc = 0.0
                out[key] = fc
            return out

        forecast = read_forecast(forecast_cols)
        cities = None
        if city_cols:
            cities = {city: CityInput(forecast=read_forecast(cols)) for city, cols in city_cols.items()}
            split = {m: sum(c.forecast.get(m, 0.0) for c in cities.values())
                     for m in sorted(set().union(*(c.forecast for c in cities.values())))}
            if not forecast_cols:
                forecast = split
            else:
                off = next((m for m in window if m in forecast and m in split
                            and abs(split[m] - forecast[m]) > CITY_TOTAL_TOLERANCE), None)
                if off is not None:
                    warnings.append(ParseWarning(
                        sap_code=sap, column=None,
                        message=f"Yangon + Mandalay forecast differs from the combined forecast in {month_label(off)}"))

        skus.append(SkuInput(
            sap_code=sap,
            supplier=_collapse(cell(c_sup)),
            description=_collapse(cell(c_desc)),
            packing_size=packing,
            moq=0.0,  # MOQ and lead time come from supplier settings
            shelf_life_months=shelf,
            lead_time_days=None,
            sellable=0.0,  # stock is filled in only by stock.apply_stock; callers must apply the stock reports
            non_sellable=0.0,
            sit=0.0,  # filled in only by sit.apply_sit from the Stock in Transit file
            mtd_sales=mtd,
            forecast=forecast,
            cities=cities,
        ))

    all_months = sorted({key for key, _, _ in forecast_cols}.union(
        *({key for key, _, _ in cols} for cols in city_cols.values())))
    return ParsedInput(
        skus=skus,
        forecast_months=[key for key, _, _ in forecast_cols] if forecast_cols else all_months,
        mtd_month=mtd_month,
        mtd_label=mtd_label,
        mtd_end=mtd_end,
        default_plan_date=mtd_end + timedelta(days=1),
        warnings=warnings,
    )


CITY_MONTH_RE = re.compile(r"^([a-z]+)'(\d{2})$")  # "oct'26", "sept'27" (normalised)
CITY_TOTAL_TOLERANCE = 0.5  # cartons: Yangon + Mandalay may differ from the combined forecast by rounding


def _city_forecast_columns(rows_above: list[tuple], header: tuple) -> dict[str, list[tuple[str, int, str]]]:
    """The Yangon / Mandalay forecast columns: month headers like "Oct'26" under a "YGN IMS" / "MDY IMS" label in the
    rows above the header row. Columns under another label ("Total IMS") or none are ignored. City -> sorted
    (YYYY-MM, column index, "<label> <header>")."""
    labels = group_labels(rows_above, len(header))
    out: dict[str, list[tuple[str, int, str]]] = {}
    for i, h in enumerate(header):
        m = CITY_MONTH_RE.match(_norm(h))
        city = label_city(labels[i]) if labels[i] else None
        if not m or city is None:
            continue
        mon = _month_number(m.group(1))
        if mon is None:
            raise InputFileError(f"Unrecognised month in forecast column header: {_collapse(h)}.")
        out.setdefault(city, []).append((f"{2000 + int(m.group(2)):04d}-{mon:02d}", i,
                                         f"{labels[i]} {_collapse(h)}"))
    # Left to right, a city's months must rise. A label typed over the wrong column pulls the next group's first
    # month in after this group's last one; refuse that rather than plan a city from another city's forecast.
    for city, cols in out.items():
        months = [key for key, _, _ in cols]   # in column order
        if any(b <= a for a, b in zip(months, months[1:])):
            raise InputFileError(
                f"The {CITY_NAME[city]} forecast columns are out of order (a month comes after a later one). Check "
                "that each 'YGN IMS' / 'MDY IMS' label sits over the first month column of its group.")
    return {city: sorted(cols) for city, cols in out.items()}


def _check_forecast_months(cols: list[tuple[str, int, str]], mtd_month: str, window: list[str], who: str,
                           warnings: list[ParseWarning]) -> None:
    """Sorted forecast columns must be consecutive months, start no later than the MTD month, and cover at least one
    window month; each missing window month is a warning. `who` is "" for the combined forecast, else "Yangon " or
    "Mandalay "."""
    def sentence(text: str) -> str:
        return text[0].upper() + text[1:]

    cols.sort()
    for (prev, _, _), (cur, _, cur_text) in zip(cols, cols[1:]):
        if cur == prev:
            raise InputFileError(sentence(f"{who}forecast month {cur} appears in more than one column ({cur_text})."))
        expected = _next_month(prev)
        if cur != expected:
            raise InputFileError(sentence(
                f"{who}forecast months must be consecutive; {expected} is missing between {prev} and {cur}."))
    if cols[0][0] > mtd_month:
        raise InputFileError(
            f"The first {who}forecast month ({cols[0][0]}) is later than the MTD month "
            f"({mtd_month}); the forecast must start no later than the MTD month.")
    present = {key for key, _, _ in cols}
    if not present.intersection(window):
        raise InputFileError(
            f"None of the forecast months used in the calculation have a {who}column: expected "
            + ", ".join(month_label(m) for m in window)
            + f" (the MTD month and the next 2), but the {who}forecast columns cover "
            f"{month_label(cols[0][0])} to {month_label(cols[-1][0])}.")
    for key in window:
        if key not in present:
            warnings.append(ParseWarning(
                sap_code=None, column=None,
                message=f"No {who}forecast column for {month_label(key)} — counted as missing"))


def drop_unused_warnings(parsed: ParsedInput) -> ParsedInput:
    """The parsed input without warnings on the shelf life or MTD columns. Runs saved before those
    warnings were dropped still store them; neither column is used in the calculation."""
    unused = {_norm("Shelf Life month"), _norm(parsed.mtd_label)}
    kept = [w for w in parsed.warnings if w.column is None or _norm(w.column) not in unused]
    return parsed.model_copy(update={"warnings": kept})
