import math
import re
from datetime import date, timedelta
from io import BytesIO

from openpyxl import load_workbook

from app.models import InputFileError, ParsedInput, ParseWarning, SkuInput

REQUIRED_COLUMNS = [
    "SAP Code",
    "By Principal",
    "Description",
    "Packing Size",
    "MOQ",
    "Shelf Life month",
    "Lead Time",
    "Total Sellable (Ctns)",
    "Total Non-Sellable (Ctns)",
    "SIT Ctns (pending order)",
]

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

    missing = [name for name in REQUIRED_COLUMNS if _norm(name) not in columns]
    if missing:
        raise InputFileError("The 'Data' sheet is missing required column(s): " + ", ".join(missing) + ".")

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
    warnings: list[ParseWarning] = []
    for n, (i, text) in columns.items():
        fm = FORECAST_RE.match(n)
        if not fm:
            if "ims" in n:
                warnings.append(ParseWarning(
                    sap_code=None, column=text,
                    message="header looks like a forecast column but does not match the expected "
                            "pattern (e.g. '2026 Oct IMS'); column ignored"))
            continue
        mon = _month_number(fm.group(2))
        if mon is None:
            raise InputFileError(f"Unrecognised month in forecast column header: {text}.")
        forecast_cols.append((f"{int(fm.group(1)):04d}-{mon:02d}", i, text))
    if not forecast_cols:
        raise InputFileError("No forecast columns found (expected headers like '2026 Oct IMS').")
    forecast_cols.sort()
    for (prev, _, _), (cur, _, cur_text) in zip(forecast_cols, forecast_cols[1:]):
        if cur == prev:
            raise InputFileError(f"Forecast month {cur} appears in more than one column ({cur_text}).")
        expected = _next_month(prev)
        if cur != expected:
            raise InputFileError(
                f"Forecast months must be consecutive; {expected} is missing between {prev} and {cur}.")
    if forecast_cols[0][0] > mtd_month:
        raise InputFileError(
            f"The first forecast month ({forecast_cols[0][0]}) is later than the MTD month "
            f"({mtd_month}); the forecast must start no later than the MTD month.")

    def col(name: str) -> tuple[int, str]:
        return columns[_norm(name)]

    c_sap, _ = col("SAP Code")
    c_sup, _ = col("By Principal")
    c_desc, _ = col("Description")
    c_pack, h_pack = col("Packing Size")
    c_moq, h_moq = col("MOQ")
    c_shelf, h_shelf = col("Shelf Life month")
    c_lead, h_lead = col("Lead Time")
    c_sell, h_sell = col("Total Sellable (Ctns)")
    c_non, h_non = col("Total Non-Sellable (Ctns)")
    c_sit, h_sit = col("SIT Ctns (pending order)")

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

        shelf_raw = cell(c_shelf)
        shelf_num = _to_number(shelf_raw)
        shelf: float | None = None
        if shelf_num is not None:
            if shelf_num <= 0:
                warnings.append(ParseWarning(
                    sap_code=sap, column=h_shelf,
                    message=("shelf life 0 treated as unknown (no cap)" if shelf_num == 0
                             else "negative shelf life treated as unknown (no cap)")))
            else:
                shelf = shelf_num
        elif shelf_raw is not None and _collapse(shelf_raw) not in ("", "-"):
            warnings.append(ParseWarning(sap_code=sap, column=h_shelf,
                                         message="non-numeric shelf life treated as unknown (no cap)"))

        lead_num = _to_number(cell(c_lead))
        if lead_num is not None:
            lead: int | None = int(round(lead_num))
        else:
            lead = None
            warnings.append(ParseWarning(sap_code=sap, column=h_lead,
                                         message="missing or non-numeric lead time"))

        mtd = num(mtd_col, mtd_label)
        if mtd < 0:
            warnings.append(ParseWarning(sap_code=sap, column=mtd_label,
                                         message="negative MTD sales (returns) treated as 0"))

        forecast: dict[str, float] = {}
        for key, i, text in forecast_cols:
            fc = num(i, text)
            if fc < 0:
                warnings.append(ParseWarning(sap_code=sap, column=text,
                                             message="negative forecast treated as 0"))
                fc = 0.0
            forecast[key] = fc

        skus.append(SkuInput(
            sap_code=sap,
            supplier=_collapse(cell(c_sup)),
            description=_collapse(cell(c_desc)),
            packing_size=packing,
            moq=num(c_moq, h_moq),
            shelf_life_months=shelf,
            lead_time_days=lead,
            sellable=num(c_sell, h_sell),
            non_sellable=num(c_non, h_non),
            sit=num(c_sit, h_sit),
            mtd_sales=mtd,
            forecast=forecast,
        ))

    return ParsedInput(
        skus=skus,
        forecast_months=[key for key, _, _ in forecast_cols],
        mtd_month=mtd_month,
        mtd_label=mtd_label,
        mtd_end=mtd_end,
        default_plan_date=mtd_end + timedelta(days=1),
        warnings=warnings,
    )
