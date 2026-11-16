"""Parser for admin's sales export, and its conversion from pieces to cartons."""
from datetime import date
from io import BytesIO

from openpyxl import load_workbook

from app.cities import CITIES, branch_city
from app.models import ActualSales, InputFileError, ParsedInput, ParseWarning, SalesExport
from app.months import month_label, prev_months
from app.parsing import _is_number, _month_number, _norm, _to_number, find_header_row

REQUIRED_COLUMNS = ["itemCode", "Year", "Month", "Qty"]


def _year_month(year_cell, month_cell) -> tuple[int, int] | None:
    """(year, month) from a sales row, or None if unreadable.

    Month may be a name (Jul, July, Sept), a number 1-12 (also as text), or an Excel date/datetime,
    in which case the date's own month and year are used and the Year cell is ignored.
    """
    if isinstance(month_cell, date):  # datetime is a date too
        return month_cell.year, month_cell.month
    year = _to_number(year_cell)
    if year is None or year != int(year) or not 1000 <= year <= 9999:
        return None
    number = _to_number(month_cell)
    if number is not None:
        month = int(number) if number == int(number) and 1 <= number <= 12 else None
    else:
        month = _month_number(_norm(month_cell))
    return None if month is None else (int(year), month)


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
            header = find_header_row(rows, REQUIRED_COLUMNS)
            if header is not None:
                found = (rows, *header)
                break
    finally:
        wb.close()
    if found is None:
        raise InputFileError("The sales export has no sheet with itemCode, Year, Month and Qty columns.")
    rows, header_idx, columns = found
    c_item, c_year, c_month, c_qty = (columns[_norm(name)] for name in REQUIRED_COLUMNS)
    c_branch = columns.get(_norm("BranchName"))

    pieces: dict[str, dict[str, float]] = {}
    city_pieces: dict[str, dict[str, dict[str, float]]] = {c: {} for c in CITIES}
    months: set[str] = set()
    warnings: list[ParseWarning] = []
    skipped = 0
    for row in rows[header_idx + 1:]:
        def cell(i: int):
            return row[i] if i < len(row) else None

        raw_item = cell(c_item)
        if raw_item is None or str(raw_item).strip() == "":
            continue
        item = str(int(raw_item)) if _is_number(raw_item) else str(raw_item).strip()

        year_month = _year_month(cell(c_year), cell(c_month))
        if year_month is None:
            skipped += 1
            warnings.append(ParseWarning(
                sap_code=item, column=None,
                message=f"could not read the year/month ({cell(c_year)!r} / {cell(c_month)!r}); row skipped"))
            continue
        key = f"{year_month[0]:04d}-{year_month[1]:02d}"

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
        city_month = city_pieces[branch_city(cell(c_branch) if c_branch is not None else None)].setdefault(item, {})
        city_month[key] = city_month.get(key, 0.0) + qty

    return SalesExport(pieces=pieces, months=sorted(months), warnings=warnings, skipped_rows=skipped,
                       city_pieces=city_pieces, has_branch=c_branch is not None)


def actual_cartons(export: SalesExport, parsed: ParsedInput) -> ActualSales:
    """Convert the export's pieces for the 3 months before the MTD month to cartons per Data SKU."""
    actual_months = prev_months(parsed.mtd_month, 3)
    present = [m for m in actual_months if m in export.months]
    if not present:
        labels = ", ".join(month_label(m) for m in actual_months)
        detail = ""
        if export.skipped_rows:
            noun = "row" if export.skipped_rows == 1 else "rows"
            detail = f" ({export.skipped_rows} {noun} had an unreadable year/month)"
        raise InputFileError(
            f"The sales export has no rows for {labels} (the 3 months before the MTD month).{detail}")

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

    # By city only when the Data sheet has the city forecast (a run split by Yangon / Mandalay).
    city_cartons = None
    if any(s.cities is not None for s in parsed.skus):
        if not export.has_branch:
            warnings.append(ParseWarning(
                sap_code=None, column=None,
                message="The Actual Sales file has no BranchName column; all its sales count as Yangon"))
        city_cartons = {}
        for city in CITIES:
            city_cartons[city] = {}
            for code, by_month in export.city_pieces.get(city, {}).items():
                used = {m: p for m, p in by_month.items() if m in present}
                if used and code in cartons:  # a usable Data SKU with a packing size
                    city_cartons[city][code] = {m: p / data_skus[code].packing_size for m, p in used.items()}

    return ActualSales(months=actual_months, cartons=cartons, skus_with_sales=len(cartons), warnings=warnings,
                       city_cartons=city_cartons)
