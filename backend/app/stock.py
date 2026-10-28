"""Parsers for the two stock reports: PG Expiry Check and PDG Stock List, turned into plain stock lines."""
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta
from io import BytesIO
from xml.etree import ElementTree

from openpyxl import load_workbook

from app.models import InputFileError, ParseWarning, StockLine, StockReport, StockSource
from app.parsing import HEADER_SEARCH_ROWS, _is_number, _norm, _to_number, find_header_row

PG_NAME = "PG Expiry Check"
PDG_NAME = "PDG Stock List"

_PG_REQUIRED = ["Item Code", "Location", "Ctn"]
_PDG_REQUIRED = ["StockCode", "Location", "Bin_Qty", "U_Ratio", "Sell or Non"]

_MAIN_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _hidden_rows(data: bytes, sheet_title: str) -> int:
    """Number of rows the sheet hides (e.g. by a filter); 0 if the workbook XML can't be read.

    Read-only openpyxl does not expose row visibility, so this reads the sheet's XML part directly.
    """
    try:
        with zipfile.ZipFile(BytesIO(data)) as z:
            rel_id = next(s.get(_REL_NS + "id")
                          for s in ElementTree.fromstring(z.read("xl/workbook.xml")).iter(_MAIN_NS + "sheet")
                          if s.get("name") == sheet_title)
            target = next(r.get("Target")
                          for r in ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(_PKG_REL_NS + "Relationship")
                          if r.get("Id") == rel_id)
            part = target[1:] if target.startswith("/") else "xl/" + target
            count = 0
            with z.open(part) as f:
                for _, el in ElementTree.iterparse(f):
                    if el.tag == _MAIN_NS + "row":
                        count += el.get("hidden") in ("1", "true")
                        el.clear()
            return count
    except Exception:
        return 0


def _load(data: bytes, required: list[str], missing_message: str):
    """(rows, header row index, normalized header -> column, sheet title) of the first sheet with the required headers."""
    try:
        wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise InputFileError("Could not read the file as an Excel .xlsx workbook.") from None
    try:
        for ws in wb.worksheets:
            ws.reset_dimensions()  # read-only mode trusts the stored sheet size, which exports sometimes get wrong
            rows = list(ws.iter_rows(values_only=True))
            header = find_header_row(rows, required)
            if header is not None:
                return rows, header[0], header[1], ws.title
    finally:
        wb.close()
    raise InputFileError(missing_message)


def _code(v) -> str:
    return str(int(v)) if _is_number(v) else str(v).strip()


def _date_part(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def _parse(data: bytes, source: StockSource, name: str, required: list[str], missing_message: str) -> StockReport:
    rows, header_idx, columns, title = _load(data, required, missing_message)
    col = {n: columns[_norm(n)] for n in required}
    c_code = col[required[0]]
    c_loc = col["Location"]

    lines: list[StockLine] = []
    skipped_codes: list[str] = []
    unknown_flags: dict[str, list] = {}  # normalized value -> [text of first occurrence, row count]
    unreadable = 0
    seen_data = False

    for row in rows[header_idx + 1:]:
        def cell(i: int):
            return row[i] if i < len(row) else None

        raw_code = cell(c_code)
        if raw_code is None or str(raw_code).strip() == "":
            continue
        seen_data = True
        code = _code(raw_code)

        if source == "PG":
            cartons = _to_number(cell(col["Ctn"]))
            flag_cell = cell(c_loc)
            flag = _norm(flag_cell)
            known = flag in ("sellable", "non-sellable")
            sellable = flag == "sellable"
        else:
            bin_qty, ratio = _to_number(cell(col["Bin_Qty"])), _to_number(cell(col["U_Ratio"]))
            cartons = bin_qty / ratio if bin_qty is not None and ratio else None
            flag_cell = cell(col["Sell or Non"])
            flag = _norm(flag_cell)
            known = flag in ("", "non")
            sellable = flag == ""

        if cartons is None:
            unreadable += 1
            if code not in skipped_codes:
                skipped_codes.append(code)
            continue
        if not known:
            entry = unknown_flags.setdefault(flag, [str(flag_cell).strip() if flag_cell is not None else "", 0])
            entry[1] += 1
        lines.append(StockLine(code=code, sellable=sellable, cartons=cartons))

    if not seen_data:
        raise InputFileError("No data rows under the header row.")

    warnings: list[ParseWarning] = []

    def warn(message: str) -> None:
        warnings.append(ParseWarning(sap_code=None, column=None, message=message))

    for value, n in unknown_flags.values():
        if source == "PG":
            warn(f"{name}: {n} rows have Location '{value}' (not Sellable or Non-Sellable); counted as non-sellable")
        else:
            warn(f"{name}: {n} rows have Sell or Non '{value}' (not blank or Non); counted as non-sellable")
    if unreadable:
        what = "Ctn" if source == "PG" else "Bin_Qty or U_Ratio"
        warn(f"{name}: {unreadable} rows have no readable {what}; skipped")
    hidden = _hidden_rows(data, title)
    if hidden:
        warn(f"{name}: {hidden} rows are hidden by a filter; they are still counted")

    as_of = _pg_as_of(rows[header_idx + 1:], columns) if source == "PG" else _pdg_as_of(rows[:header_idx])
    return StockReport(source=source, lines=lines, as_of=as_of, skipped_codes=skipped_codes, warnings=warnings)


def _pg_as_of(rows: list[tuple], columns: dict[str, int]) -> date | None:
    """Most common (expired Date - Day Left), ties going to the latest date; None if no row has both."""
    c_exp, c_left = columns.get(_norm("expired Date")), columns.get(_norm("Day Left"))
    if c_exp is None or c_left is None:
        return None
    counts: Counter[date] = Counter()
    for row in rows:
        expiry = _date_part(row[c_exp]) if c_exp < len(row) else None
        left = row[c_left] if c_left < len(row) else None
        if expiry is not None and _is_number(left):
            counts[expiry - timedelta(days=left)] += 1
    return max(counts, key=lambda d: (counts[d], d)) if counts else None


def _pdg_as_of(rows_above_header: list[tuple]) -> date | None:
    """The date in the cell directly below the 'Printed_Date' label, if there is one."""
    for r, row in enumerate(rows_above_header[:HEADER_SEARCH_ROWS]):
        for c, v in enumerate(row):
            if _norm(v) == "printed_date" and r + 1 < len(rows_above_header):
                below = rows_above_header[r + 1]
                return _date_part(below[c]) if c < len(below) else None
    return None


def parse_pg(data: bytes) -> StockReport:
    return _parse(data, "PG", PG_NAME, _PG_REQUIRED,
                  "No sheet has Item Code, Location and Ctn columns (looked in the first 10 rows of each sheet).")


def parse_pdg(data: bytes) -> StockReport:
    return _parse(data, "PDG", PDG_NAME, _PDG_REQUIRED,
                  "No sheet has StockCode, Location, Bin_Qty, U_Ratio and Sell or Non columns "
                  "(looked in the first 10 rows of each sheet).")
