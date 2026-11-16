"""Excel export of a run's holding-based order plan."""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.cities import CITY_NAME
from app.models import ParseWarning, RunRecord
from app.months import month_label
from app.sit import SIT_NAME, run_out_message
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


def _city(sku) -> str | None:
    """"Yangon" / "Mandalay" for a city row; blank for the combined rows of runs saved before the city split."""
    return CITY_NAME.get(sku.city) if sku.city else None


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
        # SIT from the Stock in Transit file and the commits entered on New plan, apart (the SKU's sit is both).
        committed = sum(a.cartons for a in (sku.sit_arrivals or []) if a.source == "commit")
        sku_rows.append([
            sku.supplier, sku.sap_code, _city(sku), sku.description, sku.status.value, _yes_no(sku.zero_forecast),
            sku.sellable, sku.pg_sellable, sku.pdg_sellable, sku.sit - committed, committed, sku.available,
            sku.pg_non_sellable, sku.pdg_non_sellable, *demand,
            sku.valid_count, sku.avg_sales, sku.holding_days, sku.buffer, sku.target, sku.required, sku.moq,
            _yes_no(sku.moq_applied), sku.order_qty, sku.stock_cover_months, sku.lead_time_days,
            sku.order_cycle_weeks, sku.next_calc_date])
    ws = wb.active
    ws.title = "SKU Plan"
    formats = {name: TWO_DECIMALS for name in ["Sellable", "PG Sellable", "PDG Sellable", "SIT", "Commit", "Available",
                                       "PG Non-Sellable", "PDG Non-Sellable", *month_headers, "Avg Sales", "Buffer",
                                       "Target"]}
    formats["Stock Cover (months)"] = ONE_DECIMAL
    _write_sheet(ws, ["Principal", "SAP Code", "Region", "Description", "Status", "Zero Forecast", "Sellable",
                      "PG Sellable", "PDG Sellable", "SIT", "Commit", "Available", "PG Non-Sellable",
                      "PDG Non-Sellable", *month_headers, "Valid Values", "Avg Sales", "Holding (days)", "Buffer", "Target",
                      "Required", "MOQ", "MOQ Applied", "Order Qty", "Stock Cover (months)",
                      "Lead Time (days)", "Order Cycle (weeks)", "Next Calculation Date"], sku_rows, formats)

    # The 12-month sheets, laid out like the plan page: settings, the 6 demand months, stock, then one order
    # column per plan month (none for runs saved before it), the total and the status. A blocked SKU's order
    # cells stay blank, and so do the order plan's months without an order. The stock group is the average monthly
    # sales, the buffer (cartons), available, and the level the orders top up to: the target, or the order plan's
    # order-up-to.
    plan_headers = [month_label(m) for m in result.plan_months]

    def month_sheet(title: str, column: str, months_of, status_of, level: str, level_of) -> None:
        rows = []
        for sku in result.skus:
            months = months_of(sku) if plan_headers else None
            orders =([p.order if p.order_month else None for p in months] if months
                      else [None] * len(plan_headers))
            total = None if months is None or sku.holding_days is None else sum(o or 0 for o in orders)
            status = status_of(sku)
            rows.append([sku.supplier, sku.sap_code, _city(sku), sku.description, sku.moq, sku.holding_days,
                         sku.lead_time_days, sku.order_cycle_weeks, *demand_row(sku), sku.avg_sales, sku.buffer, sku.available,
                         level_of(sku), *orders, total, status.value if status else None])
        _write_sheet(wb.create_sheet(title),
                     ["Principal", "SAP Code", "Region", "Description", "MOQ", "Holding (days)", "Lead Time (days)",
                      "Order Cycle (weeks)", *month_headers, "Avg Sales", "Buffer", "Available", level,
                      *[f"{h} {column}" for h in plan_headers], "12-Month Total", "Status"], rows,
                     {name: TWO_DECIMALS for name in [*month_headers, "Avg Sales", "Buffer", "Available", level]})

    month_sheet("12-Month Plan", "Order Demand Forecast", lambda s: s.monthly, lambda s: s.status,
                "Target", lambda s: s.target)
    month_sheet("Order Plan", "Order Plan", lambda s: s.order_plan, lambda s: s.plan_status,
                "Order-Up-To", lambda s: s.plan_order_up_to)

    # One row per planned order above 0, by principal and date: the purchase orders to place. Runs saved before
    # the weekly order cycle have no order plan, so the sheet has its headers only.
    order_rows = sorted(
        ([sku.supplier, sku.sap_code, _city(sku), sku.description, line.date, line.qty, _yes_no(line.moq_applied)]
         for sku in result.skus for month in (sku.order_plan or []) for line in month.orders if line.qty > 0),
        key=lambda r: (r[0], r[4], r[3], r[1], r[2] or ""))
    _write_sheet(wb.create_sheet("Order Dates"),
                 ["Principal", "SAP Code", "Region", "Description", "Order Date", "Order Qty", "MOQ Applied"], order_rows)

    # The commits entered on New plan (stock agreed with a principal, not yet in the Stock in Transit file).
    sku_info = {s.sap_code: s for s in run.parsed.skus}
    _write_sheet(wb.create_sheet("Commits"),
                 ["Principal", "SAP Code", "Description", "Region", "Cartons", "Arrival Week"],
                 [[sku_info[c.sap_code].supplier if c.sap_code in sku_info else None, c.sap_code,
                   sku_info[c.sap_code].description if c.sap_code in sku_info else None,
                   CITY_NAME.get(c.region, c.region), c.cartons, c.arrival_week] for c in run.parsed.commits])

    def months_or_blank(values: list | None) -> list:
        return values if values is not None else [None] * len(plan_headers)

    _write_sheet(wb.create_sheet("Principal Summary"),
                 ["Principal", "Holding (days)", "Order Cycle (weeks)", "SKUs", "SKUs to Order", "Total Order Qty",
                  "Order Plan SKUs to Order", "Order Plan Total Order Qty", "Blocked SKUs", "No Demand SKUs",
                  "Zero Forecast SKUs", *[f"{h} Order Demand Forecast" for h in plan_headers], "12-Month Total",
                  *[f"{h} Order Plan" for h in plan_headers], "12-Month Order Plan Total"],
                 [[s.supplier, s.holding_days, s.order_cycle_weeks, s.sku_count, s.skus_to_order,
                   s.total_order_qty, s.plan_skus_to_order, s.plan_total_order_qty, s.blocked_skus,
                   s.no_demand_skus, s.zero_forecast_skus, *months_or_blank(s.monthly_order_qty),
                   s.twelve_month_total, *months_or_blank(s.plan_monthly_order_qty), s.plan_twelve_month_total]
                  for s in summarize_suppliers(result)])

    _write_sheet(wb.create_sheet("Settings Used"),
                 ["Principal", "Holding (days)", "MOQ", "Lead Time (days)", "Order Cycle (weeks)"],
                 [[s.supplier, s.holding_days, s.moq, s.lead_time_days, s.order_cycle_weeks]
                  for s in result.settings_used])

    warnings = ([("Sales Forecast file", w) for w in run.parsed.warnings]
                + [("Actual Sales file", w) for w in run.actual.warnings]
                + [("Stock files", w) for w in (run.stock.warnings if run.stock else [])]
                + [(SIT_NAME, w) for w in (run.stock.sit_warnings if run.stock else [])]
                + [(SIT_NAME, ParseWarning(sap_code=s.sap_code, column=None,
                                           message=(f"{CITY_NAME[s.city]}: " if s.city in CITY_NAME else "")
                                           + run_out_message(s.runs_out_on, s.runs_out_arrival)))
                   for s in run.result.skus if s.runs_out_on is not None and s.runs_out_arrival is not None])
    _write_sheet(wb.create_sheet("Warnings"), ["Source", "SAP Code", "Column", "Message"],
                 [[source, w.sap_code, w.column, w.message] for source, w in warnings])

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
