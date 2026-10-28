from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel


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


class SupplierSetting(BaseModel):
    supplier: str
    reorder_days: int
    target_days: int
    is_default: bool = False


class FlagCode(str, Enum):
    ORDER_NOW = "ORDER_NOW"
    STOCKOUT_RISK = "STOCKOUT_RISK"
    EXCESS = "EXCESS"
    EXPIRY_RISK = "EXPIRY_RISK"
    NO_FORECAST_HOLDING_STOCK = "NO_FORECAST_HOLDING_STOCK"
    MTD_ABOVE_FORECAST = "MTD_ABOVE_FORECAST"
    LEAD_TIME_EXCEEDS_REORDER = "LEAD_TIME_EXCEEDS_REORDER"
    MOQ_EXCEEDS_SHELF_LIFE = "MOQ_EXCEEDS_SHELF_LIFE"
    MISSING_LEAD_TIME = "MISSING_LEAD_TIME"


class Flag(BaseModel):
    code: FlagCode
    message: str


class OrderReason(BaseModel):
    on_hand: float
    on_order: float
    inventory_position: float
    stock_at_arrival: float
    reorder_qty: float
    target_qty: float
    raw_qty: float
    moq_applied: bool
    shelf_life_cap: float | None
    cap_applied: bool


class PlannedOrder(BaseModel):
    order_date: date
    arrival_date: date
    qty: int
    reason: OrderReason


class WeekProjection(BaseModel):
    week: int  # 1-based
    start: date
    end: date
    demand: float
    arrivals: float
    closing_stock: float
    lost: float
    reorder_qty: float  # at week start
    target_qty: float  # at week start


class SkuPlan(BaseModel):
    sap_code: str
    supplier: str
    description: str
    lead_time_days: int | None
    moq: float
    shelf_life_months: float | None
    sellable: float
    non_sellable: float
    sit: float
    starting_stock: float
    days_of_cover: float | None
    total_forecast: float
    orders: list[PlannedOrder]
    weeks: list[WeekProjection]
    flags: list[Flag]
    stockout_days: int
    stockout_qty: float
    first_stockout_date: date | None


class SupplierSummary(BaseModel):
    supplier: str
    reorder_days: int
    target_days: int
    is_default: bool
    sku_count: int
    skus_to_order: int
    cartons_in_window: int
    earliest_order_date: date | None
    flag_counts: dict[str, int]
    max_lead_time_days: int | None


class PlanResult(BaseModel):
    plan_date: date
    skus: list[SkuPlan]
    settings_used: list[SupplierSetting]
    new_suppliers: list[str]
    flag_counts: dict[str, int]


class RunListItem(BaseModel):
    id: int
    created_at: datetime
    file_name: str
    plan_date: date
    sku_count: int


class RunRecord(RunListItem):
    parsed: ParsedInput
    result: PlanResult


class SupplierSettingView(SupplierSetting):
    max_lead_time_days: int | None
    sku_count: int


class InspectResponse(BaseModel):
    file_name: str
    sku_count: int
    supplier_count: int
    forecast_months: list[str]
    mtd_label: str
    mtd_end: date
    default_plan_date: date
    min_plan_date: date
    max_plan_date: date
    warnings: list[ParseWarning]


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
