"""Parser for admin's sales export, and its conversion from pieces to cartons."""
from io import BytesIO

from openpyxl import load_workbook

from app.models import ActualSales, InputFileError, ParsedInput, ParseWarning, SalesExport
from app.months import month_label, prev_months
from app.parsing import HEADER_SEARCH_ROWS, _is_number, _month_number, _norm, _to_number

REQUIRED_COLUMNS = ["itemCode", "Year", "Month", "Qty"]


def _find_header(rows: list[tuple]) -> tuple[int, dict[str, int]] | None:
    """(row index, normalized header -> column index) of the first header row with all required columns."""
    for i, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        columns: dict[str, int] = {}
        for c, h in enumerate(row):
            if _norm(h):
                columns.setdefault(_norm(h), c)
        if all(_norm(name) in columns for name in REQUIRED_COLUMNS):
            return i, columns
    return None


def parse_sales(data: bytes) -> SalesExport:
    try:
        wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise InputFileError("Could not read the sales export as an Excel .xlsx workbook.") from None
    try:
        found = None
        for ws in wb.worksheets:
            ws.reset_dimensions()  # read-only mode trusts the stored sheet size, which exports sometimes get wrong
            rows = list(ws.iter_rows(values_only=True))
            header = _find_header(rows)
            if header is not None:
                found = (rows, *header)
                break
    finally:
        wb.close()
    if found is None:
        raise InputFileError("The sales export has no sheet with itemCode, Year, Month and Qty columns.")
    rows, header_idx, columns = found
    c_item, c_year, c_month, c_qty = (columns[_norm(name)] for name in REQUIRED_COLUMNS)

    pieces: dict[str, dict[str, float]] = {}
    months: set[str] = set()
    warnings: list[ParseWarning] = []
    for row in rows[header_idx + 1:]:
        def cell(i: int):
            return row[i] if i < len(row) else None

        raw_item = cell(c_item)
        if raw_item is None or str(raw_item).strip() == "":
            continue
        item = str(int(raw_item)) if _is_number(raw_item) else str(raw_item).strip()

        year, month = _to_number(cell(c_year)), _month_number(_norm(cell(c_month)))
        if year is None or month is None or year != int(year):
            warnings.append(ParseWarning(
                sap_code=item, column=None,
                message=f"could not read the year/month ({cell(c_year)!r} / {cell(c_month)!r}); row skipped"))
            continue
        key = f"{int(year):04d}-{month:02d}"

        raw_qty = cell(c_qty)
        qty = _to_number(raw_qty)
        if qty is None:
            warnings.append(ParseWarning(
                sap_code=item, column="Qty",
                message=f"non-numeric Qty {raw_qty!r} for {month_label(key)}; row skipped"))
            continue

        months.add(key)
        by_month = pieces.setdefault(item, {})
        by_month[key] = by_month.get(key, 0.0) + qty

    return SalesExport(pieces=pieces, months=sorted(months), warnings=warnings)


def actual_cartons(export: SalesExport, parsed: ParsedInput) -> ActualSales:
    """Convert the export's pieces for the 3 months before the MTD month to cartons per Data SKU."""
    actual_months = prev_months(parsed.mtd_month, 3)
    present = [m for m in actual_months if m in export.months]
    if not present:
        labels = ", ".join(month_label(m) for m in actual_months)
        raise InputFileError(f"The sales export has no rows for {labels} (the 3 months before the MTD month).")

    warnings: list[ParseWarning] = list(export.warnings)
    for m in actual_months:
        if m not in present:
            warnings.append(ParseWarning(
                sap_code=None, column=None,
                message=f"No sales rows for {month_label(m)} - counted as missing"))
    for m in export.months:
        if m not in actual_months:
            warnings.append(ParseWarning(
                sap_code=None, column=None,
                message=f"The sales export has rows for {month_label(m)}, which is not one of the "
                        f"3 actual months; ignored"))

    data_skus = {s.sap_code: s for s in parsed.skus}
    cartons: dict[str, dict[str, float]] = {}
    for code, by_month in export.pieces.items():
        used = {m: p for m, p in by_month.items() if m in present}
        if not used:
            continue
        sku = data_skus.get(code)
        if sku is None:
            warnings.append(ParseWarning(
                sap_code=code, column=None,
                message="item is in the sales export but not in the Data sheet; ignored"))
        elif sku.packing_size is None or sku.packing_size <= 0:
            warnings.append(ParseWarning(
                sap_code=code, column="Packing Size",
                message="has sales but no usable packing size; its actuals count as missing"))
        else:
            cartons[code] = {m: p / sku.packing_size for m, p in used.items()}

    return ActualSales(months=actual_months, cartons=cartons, skus_with_sales=len(cartons), warnings=warnings)
