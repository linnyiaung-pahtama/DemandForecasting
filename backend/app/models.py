from datetime import date, datetime
from datetime import date as _date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, model_validator


class InputFileError(Exception):
    """Raised for an unusable input file; the message is shown to the user."""


class SitArrival(BaseModel):
    """Stock in transit landing on a day: the Monday of its arrival week. Kept as in the file; only the calculation
    moves an arrival dated before the plan date to the plan date."""
    date: _date
    cartons: float
    source: Literal["sit", "commit"] = "sit"  # the Stock in Transit file, or a commit entered on New plan


class Commit(BaseModel):
    """Stock already agreed with a principal but not yet in the Stock in Transit file, entered by hand on New plan:
    it is treated exactly like stock in transit arriving in that week and region."""
    sap_code: str
    cartons: float
    arrival_week: _date  # the Monday of the estimated arrival week
    region: str  # "YGN" / "MDY"


class CityInput(BaseModel):
    """One city's share of a SKU's inputs: its stock (from the stock reports' branches), its stock in transit and
    its forecast (from the Data sheet's YGN IMS / MDY IMS columns)."""
    sellable: float = 0.0
    non_sellable: float = 0.0
    pg_sellable: float = 0.0
    pdg_sellable: float = 0.0
    pg_non_sellable: float = 0.0
    pdg_non_sellable: float = 0.0
    sit: float = 0.0
    sit_arrivals: list[SitArrival] = []
    forecast: dict[str, float] = {}  # "YYYY-MM" -> cartons


class SkuInput(BaseModel):
    sap_code: str
    supplier: str
    description: str
    packing_size: float | None
    moq: float
    shelf_life_months: float | None
    lead_time_days: int | None
    sellable: float
    non_sellable: float
    sit: float
    mtd_sales: float  # raw value, may be negative
    forecast: dict[str, float]  # "YYYY-MM" -> cartons, ordered by month
    pg_sellable: float | None = None  # None only in runs saved before stock came from the stock reports
    pdg_sellable: float | None = None
    pg_non_sellable: float | None = None
    pdg_non_sellable: float | None = None
    # From the Stock in Transit file, sorted by date (sit is their total). None in runs saved before the file existed,
    # whose SIT counts as arriving on the plan date.
    sit_arrivals: list[SitArrival] | None = None
    # Yangon ("YGN") and Mandalay ("MDY") inputs; the fields above are their sums. None in runs saved before the
    # city split (and for a Data sheet without city forecast columns), which plan one combined row per SKU.
    cities: dict[str, CityInput] | None = None


class ParseWarning(BaseModel):
    sap_code: str | None
    column: str | None
    message: str


class ParsedInput(BaseModel):
    skus: list[SkuInput]
    forecast_months: list[str]
    mtd_month: str  # "YYYY-MM"
    mtd_label: str  # header text
    mtd_end: date
    default_plan_date: date
    warnings: list[ParseWarning]
    commits: list[Commit] = []  # entered on New plan; already added to the SKUs' stock in transit


class SalesExport(BaseModel):
    pieces: dict[str, dict[str, float]]  # sap code -> "YYYY-MM" -> summed pieces
    months: list[str]  # sorted "YYYY-MM" months with at least one row
    warnings: list[ParseWarning]
    skipped_rows: int = 0  # rows skipped because their year/month could not be read
    city_pieces: dict[str, dict[str, dict[str, float]]] = {}  # city -> sap code -> "YYYY-MM" -> pieces
    has_branch: bool = False  # the export has a BranchName column (without it every row counts as Yangon)


class ActualSales(BaseModel):
    months: list[str]  # the 3 actual months, oldest first
    cartons: dict[str, dict[str, float]]  # Data SAP code -> "YYYY-MM" -> cartons (months present in the export)
    skus_with_sales: int  # Data SKUs with at least one export row in the actual months
    warnings: list[ParseWarning]
    # The same per city ("YGN" / "MDY"); None in runs saved before the city split.
    city_cartons: dict[str, dict[str, dict[str, float]]] | None = None


StockSource = Literal["PG", "PDG"]


class StockLine(BaseModel):
    code: str  # normalised like Data SAP codes
    sellable: bool
    cartons: float
    city: str = "YGN"  # from PG BranchName / PDG WH B


class StockReport(BaseModel):
    source: StockSource
    lines: list[StockLine]
    as_of: date | None  # PDG: Printed_Date; PG: most common (expired Date - Day Left)
    skipped_codes: list[str]  # codes of rows skipped for an unreadable quantity (distinct, in file order)
    warnings: list[ParseWarning]  # file-level; every message starts with the report name
    has_city: bool = False  # the report has its city column (PG BranchName / PDG WH B); without it all is Yangon


class StockFileSummary(BaseModel):
    source: StockSource
    as_of: date | None
    skus_with_stock: int  # Data SKUs with at least one line in this file
    sellable_cartons: float  # summed over Data SKUs only
    non_sellable_cartons: float


class StockResult(BaseModel):
    pg: StockFileSummary
    pdg: StockFileSummary
    skus_with_stock: int  # Data SKUs with a line in either file
    warnings: list[ParseWarning]  # report warnings (PG then PDG), then merge warnings
    # The Stock in Transit file's summary and warnings; None / empty for runs saved before that file.
    sit: "SitFileSummary | None" = None
    sit_warnings: list[ParseWarning] = []


class SitLine(BaseModel):
    """One SKU's cartons under one arrival label ("<month> W<week> Arrival"), summed over the file's columns and rows."""
    code: str
    month: int  # 1-12
    week: int  # 1-5
    cartons: float
    city: str = "YGN"  # from the YGN / MDY label above the column


class SitReport(BaseModel):
    lines: list[SitLine]
    codes: list[str] = []  # every SAP code with a row, blank rows included (distinct, in file order)
    warnings: list[ParseWarning]  # per cell, with the SAP code and column


class SitFileSummary(BaseModel):
    skus_with_sit: int  # Sales Forecast SKUs with SIT above 0
    cartons: float
    first_arrival: date | None
    last_arrival: date | None


StockResult.model_rebuild()  # its `sit` field refers to SitFileSummary, defined after it


class SkuOption(BaseModel):
    """A Sales Forecast SKU for the New plan page's commit picker."""
    sap_code: str
    description: str
    supplier: str


class InspectResponse(BaseModel):
    file_name: str
    sales_file_name: str
    pg_file_name: str
    pdg_file_name: str
    sit_file_name: str
    sku_count: int
    supplier_count: int
    forecast_months: list[str]  # all forecast columns found in the Data file
    actual_months: list[str]  # the 3 months before the MTD month
    forecast_window: list[str]  # the MTD month and the next 2
    skus_with_sales: int
    mtd_label: str
    mtd_end: date
    default_plan_date: date
    min_plan_date: date
    max_plan_date: date
    stock: StockResult
    warnings: list[ParseWarning]  # Data file, sales export, stock report and merge, stock date, then SIT file warnings
    skus: list[SkuOption] = []  # every Sales Forecast SKU, for the commit picker


class SkuStatus(str, Enum):
    TO_ORDER = "TO_ORDER"
    NO_ORDER_NEEDED = "NO_ORDER_NEEDED"
    HOLDING_NOT_SET = "HOLDING_NOT_SET"
    NO_DEMAND_DATA = "NO_DEMAND_DATA"


class DemandValue(BaseModel):
    month: str  # "YYYY-MM"
    source: Literal["actual", "forecast"]
    value: float | None
    valid: bool


class OrderLine(BaseModel):
    """One planned order of the order plan: the date it is placed and its quantity."""
    date: _date  # the alias keeps the field name from shadowing the type
    qty: int
    moq_applied: bool = False


class MonthPlan(BaseModel):
    month: str  # "YYYY-MM"
    opening: float
    demand: float
    order: int | None  # None when holding is not set; in the order plan, the sum of the month's orders
    moq_applied: bool = False
    closing: float
    order_month: bool = True  # False only for order-plan months without an order date
    orders: list[OrderLine] = []  # the order plan's orders dated in this month; empty in the forecast
    # The order plan's SIT landing in this month (closing = opening + arrivals + order - demand). None in the forecast
    # and in order plans saved before arrival days, whose opening already included all SIT.
    arrivals: float | None = None


class SkuResult(BaseModel):
    sap_code: str
    supplier: str
    description: str
    packing_size: float | None
    lead_time_days: int | None
    moq: float
    sellable: float
    sit: float
    available: float
    pg_sellable: float | None = None  # breakdown of sellable, copied from SkuInput; None in older runs
    pdg_sellable: float | None = None
    pg_non_sellable: float | None = None
    pdg_non_sellable: float | None = None
    demand_values: list[DemandValue]  # actuals then forecasts, oldest first
    valid_count: int
    avg_sales: float | None  # average monthly sales of the valid values; None with no demand data
    buffer: float | None  # cartons: avg_sales / 30 x holding_days; None when holding is not set
    holding_days: float | None
    target: float | None
    required: int | None
    order_qty: int | None
    moq_applied: bool
    stock_cover_months: float | None
    next_calc_date: date | None
    status: SkuStatus
    zero_forecast: bool
    monthly: list[MonthPlan] | None = None  # the 12-month plan; None for runs saved before it
    # The order plan (ordering every order_cycle_weeks from the plan date) and its this-month values; the fields
    # above are the order demand forecast's. All None / False for runs saved before the weekly order cycle.
    order_cycle_weeks: int | None = None
    order_plan: list[MonthPlan] | None = None
    plan_order_up_to: float | None = None
    plan_required: int | None = None
    plan_order_qty: int | None = None
    plan_moq_applied: bool = False
    plan_status: SkuStatus | None = None
    # The SKU's SIT arrivals, copied from SkuInput (None in runs saved before the Stock in Transit file), and the
    # run-out flag: the day sellable stock plus arrivals so far, less demand, first falls below 0 before SIT still
    # due arrives, and that next arrival. Both None when not flagged.
    sit_arrivals: list[SitArrival] | None = None
    runs_out_on: date | None = None
    runs_out_arrival: date | None = None
    # The city this row plans ("YGN" / "MDY"): a SKU has a row per city with something in it. None for the one
    # combined row per SKU of runs saved before the city split.
    city: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _from_month_holding(cls, data: Any) -> Any:
        """A run saved while holding was in months stored `buffer` as the monthly average and had no average of
        its own; its target (average x holding months) is the buffer in cartons."""
        if isinstance(data, dict) and "holding_months" in data and "holding_days" not in data:
            data = {**data, "avg_sales": data.get("buffer"), "buffer": data.get("target"),
                    "holding_days": _months_to_days(data["holding_months"])}
        return data


DEFAULT_ORDER_CYCLE_WEEKS = 4  # for a principal whose cycle has not been entered
DAYS_PER_MONTH = 30  # holding days per month: buffer = average monthly sales / 30 x holding days


def _months_to_days(months: float | None) -> float | None:
    return None if months is None else months * DAYS_PER_MONTH


class SupplierSettings(BaseModel):
    supplier: str
    holding_days: float | None
    moq: float | None = None  # None only in runs saved before MOQ moved to supplier settings
    lead_time_days: int | None = None
    order_cycle_weeks: int | None = None  # None only in runs saved before the weekly order cycle

    @model_validator(mode="before")
    @classmethod
    def _from_month_holding(cls, data: Any) -> Any:
        """Runs saved while holding was in months: 1 month counts as 30 days."""
        if isinstance(data, dict) and "holding_months" in data and "holding_days" not in data:
            data = {**data, "holding_days": _months_to_days(data["holding_months"])}
        return data


# "holding_months" and "order_cycle_months" only appear in change-log lines written before those settings moved
# to days and weeks.
SettingField = Literal["holding_days", "moq", "lead_time_days", "order_cycle_weeks", "holding_months",
                       "order_cycle_months"]


class SettingsLogEntry(BaseModel):
    id: int
    supplier: str
    field: SettingField
    old_value: float | None
    new_value: float | None
    changed_at: datetime


class HoldingPlan(BaseModel):
    plan_date: date
    actual_months: list[str]
    forecast_months: list[str]  # the 3 used
    plan_months: list[str] = []  # the 12 months of the 12-month plan; empty for runs saved before it
    skus: list[SkuResult]
    settings_used: list[SupplierSettings]
    blocked_suppliers: list[str]
    counts: dict[str, int]  # TO_ORDER, NO_ORDER_NEEDED, HOLDING_NOT_SET, NO_DEMAND_DATA, ZERO_FORECAST
    plan_counts: dict[str, int] | None = None  # the same keys by order-plan status; None for older runs


class RunListItem(BaseModel):
    id: int
    created_at: datetime
    file_name: str
    sales_file_name: str
    pg_file_name: str | None = None  # None for runs saved before the stock reports
    pdg_file_name: str | None = None
    sit_file_name: str | None = None  # None for runs saved before the Stock in Transit file
    plan_date: date
    sku_count: int


class RunRecord(RunListItem):
    parsed: ParsedInput
    actual: ActualSales
    result: HoldingPlan
    stock: StockResult | None = None  # None for runs saved before the stock reports


class SupplierSummary(BaseModel):
    supplier: str
    holding_days: float | None
    sku_count: int
    skus_to_order: int
    total_order_qty: int
    blocked_skus: int
    no_demand_skus: int
    zero_forecast_skus: int
    moq: float | None  # from the plan's settings_used; None for runs saved before supplier MOQ/lead time
    lead_time_days: int | None
    monthly_order_qty: list[int] | None = None  # per plan month; None for runs saved before the 12-month plan
    twelve_month_total: int | None = None
    # The order plan's figures. None for runs saved before the weekly order cycle; the monthly totals are
    # also None for a principal whose holding is not set, and None in months without an order date.
    order_cycle_weeks: int | None = None
    plan_skus_to_order: int | None = None
    plan_total_order_qty: int | None = None
    plan_monthly_order_qty: list[int | None] | None = None
    plan_twelve_month_total: int | None = None


class SupplierSettingView(BaseModel):
    supplier: str
    holding_days: float | None
    moq: float
    lead_time_days: int | None
    order_cycle_weeks: int
    sku_count: int
