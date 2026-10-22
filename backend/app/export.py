"""Excel export of a run's order plan."""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.models import RunRecord
from app.summary import orders_in_window, summarize_suppliers

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DATE_FORMAT = "yyyy-mm-dd"


def _write_sheet(ws: Worksheet, headers: list[str], rows: list[list]) -> None:
    ws.append(headers)
    for row in rows:
        ws.append(row)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    for idx, header in enumerate(headers, start=1):
        width = max([len(header)] + [len(str(r[idx - 1])) for r in rows if r[idx - 1] is not None])
        ws.column_dimensions[get_column_letter(idx)].width = min(max(width + 2, 10), 60)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            if hasattr(cell.value, "year"):
                cell.number_format = DATE_FORMAT


def build_export(run: RunRecord, window_weeks: int = 4) -> bytes:
    result = run.result
    wb = Workbook()

    sku_rows = []
    for sku in result.skus:
        first = min(sku.orders, key=lambda o: o.order_date) if sku.orders else None
        window_qty = sum(o.qty for o in orders_in_window(sku, result.plan_date, window_weeks))
        sku_rows.append([
            sku.supplier, sku.sap_code, sku.description, sku.sellable, sku.sit, sku.non_sellable,
            sku.days_of_cover, sku.lead_time_days,
            first.order_date if first else None, first.qty if first else None,
            first.arrival_date if first else None, window_qty,
            ", ".join(f.code.value for f in sku.flags)])
    ws = wb.active
    ws.title = "SKU Plan"
    _write_sheet(ws, ["Supplier", "SAP Code", "Description", "Sellable", "SIT", "Non-Sellable",
                      "Days of Cover", "Lead Time", "Next Order Date", "Next Order Qty",
                      "Next Arrival", "Orders in Window (cartons)", "Flags"], sku_rows)

    order_rows = [
        [sku.supplier, sku.sap_code, sku.description, o.order_date, o.arrival_date, o.qty,
         o.reason.inventory_position, o.reason.reorder_qty, o.reason.target_qty,
         "Yes" if o.reason.moq_applied else "No", o.reason.shelf_life_cap]
        for sku in result.skus for o in sku.orders]
    _write_sheet(wb.create_sheet("Orders"),
                 ["Supplier", "SAP Code", "Description", "Order Date", "Arrival Date", "Qty",
                  "Inventory Position", "Reorder Qty", "Target Qty", "MOQ Applied", "Shelf-Life Cap"],
                 order_rows)

    summary_rows = [
        [s.supplier, s.reorder_days, s.target_days, "Yes" if s.is_default else "No", s.sku_count,
         s.skus_to_order, s.cartons_in_window, s.earliest_order_date]
        for s in summarize_suppliers(result, window_weeks)]
    _write_sheet(wb.create_sheet("Supplier Summary"),
                 ["Supplier", "Reorder Days", "Target Days", "Default Settings", "SKUs",
                  "SKUs to Order", "Cartons in Window", "Earliest Order Date"], summary_rows)

    _write_sheet(wb.create_sheet("Settings Used"), ["Supplier", "Reorder Days", "Target Days", "Default"],
                 [[s.supplier, s.reorder_days, s.target_days, "Yes" if s.is_default else "No"]
                  for s in result.settings_used])

    _write_sheet(wb.create_sheet("Warnings"), ["SAP Code", "Column", "Message"],
                 [[w.sap_code, w.column, w.message] for w in run.parsed.warnings])

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
