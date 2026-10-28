from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, StrictFloat, StrictInt


class InputFileError(Exception):
    """Raised for an unusable input file; the message is shown to the user."""


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


class SalesExport(BaseModel):
    pieces: dict[str, dict[str, float]]  # sap code -> "YYYY-MM" -> summed pieces
    months: list[str]  # sorted "YYYY-MM" months with at least one row
    warnings: list[ParseWarning]


class ActualSales(BaseModel):
    months: list[str]  # the 3 actual months, oldest first
    cartons: dict[str, dict[str, float]]  # Data SAP code -> "YYYY-MM" -> cartons (months present in the export)
    skus_with_sales: int  # Data SKUs with at least one export row in the actual months
    warnings: list[ParseWarning]


class InspectResponse(BaseModel):
    file_name: str
    sales_file_name: str
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
    warnings: list[ParseWarning]  # Data file warnings, then sales export warnings


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
    demand_values: list[DemandValue]  # actuals then forecasts, oldest first
    valid_count: int
    buffer: float | None
    holding_months: float | None
    target: float | None
    required: int | None
    order_qty: int | None
    moq_applied: bool
    stock_cover_months: float | None
    next_calc_date: date | None
    status: SkuStatus
    zero_forecast: bool


class SupplierHolding(BaseModel):
    supplier: str
    holding_months: StrictFloat | StrictInt | None


class SettingsLogEntry(BaseModel):
    id: int
    supplier: str
    old_value: float | None
    new_value: float | None
    changed_at: datetime


class HoldingPlan(BaseModel):
    plan_date: date
    actual_months: list[str]
    forecast_months: list[str]  # the 3 used
    skus: list[SkuResult]
    settings_used: list[SupplierHolding]
    blocked_suppliers: list[str]
    counts: dict[str, int]  # TO_ORDER, NO_ORDER_NEEDED, HOLDING_NOT_SET, NO_DEMAND_DATA, ZERO_FORECAST


class RunListItem(BaseModel):
    id: int
    created_at: datetime
    file_name: str
    sales_file_name: str
    plan_date: date
    sku_count: int


class RunRecord(RunListItem):
    parsed: ParsedInput
    actual: ActualSales
    result: HoldingPlan


class SupplierSummary(BaseModel):
    supplier: str
    holding_months: float | None
    sku_count: int
    skus_to_order: int
    total_order_qty: int
    blocked_skus: int
    no_demand_skus: int
    zero_forecast_skus: int
    max_lead_time_days: int | None


class SupplierSettingView(BaseModel):
    supplier: str
    holding_months: float | None
    sku_count: int
    max_lead_time_days: int | None
