"""Excel export of a run's holding-based order plan."""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.models import RunRecord
from app.months import month_label
from app.summary import summarize_suppliers

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DATE_FORMAT = "yyyy-mm-dd"
TWO_DECIMALS = "0.00"
ONE_DECIMAL = "0.0"


def _safe(value):
    """Make a string cell safe to open in Excel: drop characters openpyxl rejects and stop it being read
    as a formula (only a leading "=" makes Excel read text as one). Numbers, dates and None pass through
    unchanged."""
    if not isinstance(value, str):
        return value
    value = ILLEGAL_CHARACTERS_RE.sub("", value)
    return "'" + value if value.startswith("=") else value


def _yes_no(flag: bool) -> str:
    return "Yes" if flag else "No"


def _write_sheet(ws: Worksheet, headers: list[str], rows: list[list],
                 formats: dict[str, str] | None = None) -> None:
    ws.append(headers)
    for row in rows:
        ws.append([_safe(v) for v in row])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    for idx, header in enumerate(headers, start=1):
        width = max([len(header)] + [len(str(r[idx - 1])) for r in rows if r[idx - 1] is not None])
        ws.column_dimensions[get_column_letter(idx)].width = min(max(width + 2, 10), 60)
    column_formats = formats or {}
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            if hasattr(cell.value, "year"):
                cell.number_format = DATE_FORMAT
            elif headers[cell.column - 1] in column_formats:
                cell.number_format = column_formats[headers[cell.column - 1]]


def build_export(run: RunRecord) -> bytes:
    result = run.result
    wb = Workbook()

    month_headers = ([f"{month_label(m)} Actual" for m in result.actual_months]
                     + [f"{month_label(m)} Sales Forecast" for m in result.forecast_months])

    def demand_row(sku) -> list:
        by_month = {(d.source, d.month): d.value for d in sku.demand_values}
        return ([by_month.get(("actual", m)) for m in result.actual_months]
                + [by_month.get(("forecast", m)) for m in result.forecast_months])

    sku_rows = []
    for sku in result.skus:
        demand = demand_row(sku)
        sku_rows.append([
            sku.supplier, sku.sap_code, sku.description, sku.status.value, _yes_no(sku.zero_forecast),
            sku.sellable, sku.pg_sellable, sku.pdg_sellable, sku.sit, sku.available,
            sku.pg_non_sellable, sku.pdg_non_sellable, *demand,
            sku.valid_count, sku.buffer, sku.holding_months, sku.target, sku.required, sku.moq,
            _yes_no(sku.moq_applied), sku.order_qty, sku.stock_cover_months, sku.lead_time_days,
            sku.order_cycle_months, sku.next_calc_date])
    ws = wb.active
    ws.title = "SKU Plan"
    formats = {name: TWO_DECIMALS for name in ["Sellable", "PG Sellable", "PDG Sellable", "SIT", "Available",
                                       "PG Non-Sellable", "PDG Non-Sellable", *month_headers, "Buffer", "Target"]}
    formats["Stock Cover (months)"] = ONE_DECIMAL
    _write_sheet(ws, ["Principal", "SAP Code", "Description", "Status", "Zero Forecast", "Sellable",
                      "PG Sellable", "PDG Sellable", "SIT", "Available", "PG Non-Sellable",
                      "PDG Non-Sellable", *month_headers, "Valid Values", "Buffer", "Holding (months)", "Target",
                      "Required", "MOQ", "MOQ Applied", "Order Qty", "Stock Cover (months)",
                      "Lead Time (days)", "Order Cycle (months)", "Next Calculation Date"], sku_rows, formats)

    # The 12-month sheets, laid out like the plan page: settings, the 6 demand months, stock, then one order
    # column per plan month (none for runs saved before it), the total and the status. A blocked SKU's order
    # cells stay blank, and so do the order plan's months between orders.
    plan_headers = [month_label(m) for m in result.plan_months]

    def month_sheet(title: str, column: str, months_of, status_of) -> None:
        rows = []
        for sku in result.skus:
            months = months_of(sku) if plan_headers else None
            orders =([p.order if p.order_month else None for p in months] if months
                      else [None] * len(plan_headers))
            total = None if months is None or sku.holding_months is None else sum(o or 0 for o in orders)
            status = status_of(sku)
            rows.append([sku.supplier, sku.sap_code, sku.description, sku.moq, sku.holding_months,
                         sku.lead_time_days, sku.order_cycle_months, *demand_row(sku), sku.buffer, sku.available,
                         sku.target, *orders, total, status.value if status else None])
        _write_sheet(wb.create_sheet(title),
                     ["Principal", "SAP Code", "Description", "MOQ", "Holding (months)", "Lead Time (days)",
                      "Order Cycle (months)", *month_headers, "Buffer", "Available", "Target",
                      *[f"{h} {column}" for h in plan_headers], "12-Month Total", "Status"], rows,
                     {name: TWO_DECIMALS for name in [*month_headers, "Buffer", "Available", "Target"]})

    month_sheet("12-Month Plan", "Order Demand Forecast", lambda s: s.monthly, lambda s: s.status)
    month_sheet("Order Plan", "Order Plan", lambda s: s.order_plan, lambda s: s.plan_status)

    def months_or_blank(values: list | None) -> list:
        return values if values is not None else [None] * len(plan_headers)

    _write_sheet(wb.create_sheet("Principal Summary"),
                 ["Principal", "Holding (months)", "Order Cycle (months)", "SKUs", "SKUs to Order", "Total Order Qty",
                  "Order Plan SKUs to Order", "Order Plan Total Order Qty", "Blocked SKUs", "No Demand SKUs",
                  "Zero Forecast SKUs", *[f"{h} Order Demand Forecast" for h in plan_headers], "12-Month Total",
                  *[f"{h} Order Plan" for h in plan_headers], "12-Month Order Plan Total"],
                 [[s.supplier, s.holding_months, s.order_cycle_months, s.sku_count, s.skus_to_order,
                   s.total_order_qty, s.plan_skus_to_order, s.plan_total_order_qty, s.blocked_skus,
                   s.no_demand_skus, s.zero_forecast_skus, *months_or_blank(s.monthly_order_qty),
                   s.twelve_month_total, *months_or_blank(s.plan_monthly_order_qty), s.plan_twelve_month_total]
                  for s in summarize_suppliers(result)])

    _write_sheet(wb.create_sheet("Settings Used"),
                 ["Principal", "Holding (months)", "MOQ", "Lead Time (days)", "Order Cycle (months)"],
                 [[s.supplier, s.holding_months, s.moq, s.lead_time_days, s.order_cycle_months]
                  for s in result.settings_used])

    warnings = ([("Data file", w) for w in run.parsed.warnings]
                + [("Sales export", w) for w in run.actual.warnings]
                + [("Stock files", w) for w in (run.stock.warnings if run.stock else [])])
    _write_sheet(wb.create_sheet("Warnings"), ["Source", "SAP Code", "Column", "Message"],
                 [[source, w.sap_code, w.column, w.message] for source, w in warnings])

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
