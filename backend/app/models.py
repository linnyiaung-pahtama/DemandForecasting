from datetime import date

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
