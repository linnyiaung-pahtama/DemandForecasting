// Mirrors backend/app/models.py field-for-field. Dates are ISO strings (YYYY-MM-DD),
// datetimes are ISO date-time strings. SalesExport is backend-only and has no type here.

export interface SkuInput {
  sap_code: string
  supplier: string
  description: string
  packing_size: number | null
  moq: number
  shelf_life_months: number | null
  lead_time_days: number | null
  sellable: number
  non_sellable: number
  sit: number
  mtd_sales: number // raw value, may be negative
  forecast: Record<string, number> // "YYYY-MM" -> cartons, ordered by month
}

export interface ParseWarning {
  sap_code: string | null
  column: string | null
  message: string
}

export interface ParsedInput {
  skus: SkuInput[]
  forecast_months: string[]
  mtd_month: string // "YYYY-MM"
  mtd_label: string // header text
  mtd_end: string
  default_plan_date: string
  warnings: ParseWarning[]
}

export interface ActualSales {
  months: string[] // the 3 actual months, oldest first
  cartons: Record<string, Record<string, number>> // Data SAP code -> "YYYY-MM" -> cartons (months present in the export)
  skus_with_sales: number // Data SKUs with at least one export row in the actual months
  warnings: ParseWarning[]
}

export interface InspectResponse {
  file_name: string
  sales_file_name: string
  sku_count: number
  supplier_count: number
  forecast_months: string[] // all forecast columns found in the Data file
  actual_months: string[] // the 3 months before the MTD month
  forecast_window: string[] // the MTD month and the next 2
  skus_with_sales: number
  mtd_label: string
  mtd_end: string
  default_plan_date: string
  min_plan_date: string
  max_plan_date: string
  warnings: ParseWarning[] // Data file warnings, then sales export warnings
}

export type SkuStatus = 'TO_ORDER' | 'NO_ORDER_NEEDED' | 'HOLDING_NOT_SET' | 'NO_DEMAND_DATA'

export interface DemandValue {
  month: string // "YYYY-MM"
  source: 'actual' | 'forecast'
  value: number | null
  valid: boolean
}

export interface SkuResult {
  sap_code: string
  supplier: string
  description: string
  packing_size: number | null
  lead_time_days: number | null
  moq: number
  sellable: number
  sit: number
  available: number
  demand_values: DemandValue[] // actuals then forecasts, oldest first
  valid_count: number
  buffer: number | null
  holding_months: number | null
  target: number | null
  required: number | null
  order_qty: number | null
  moq_applied: boolean
  stock_cover_months: number | null
  next_calc_date: string | null
  status: SkuStatus
  zero_forecast: boolean
}

export interface SupplierHolding {
  supplier: string
  holding_months: number | null
}

export interface SettingsLogEntry {
  id: number
  supplier: string
  old_value: number | null
  new_value: number | null
  changed_at: string
}

export interface HoldingPlan {
  plan_date: string
  actual_months: string[]
  forecast_months: string[] // the 3 used
  skus: SkuResult[]
  settings_used: SupplierHolding[]
  blocked_suppliers: string[]
  counts: Record<string, number> // TO_ORDER, NO_ORDER_NEEDED, HOLDING_NOT_SET, NO_DEMAND_DATA, ZERO_FORECAST
}

export interface RunListItem {
  id: number
  created_at: string
  file_name: string
  sales_file_name: string
  plan_date: string
  sku_count: number
}

export interface RunRecord extends RunListItem {
  parsed: ParsedInput
  actual: ActualSales
  result: HoldingPlan
}

export interface SupplierSummary {
  supplier: string
  holding_months: number | null
  sku_count: number
  skus_to_order: number
  total_order_qty: number
  blocked_skus: number
  no_demand_skus: number
  zero_forecast_skus: number
  max_lead_time_days: number | null
}

export interface SupplierSettingView {
  supplier: string
  holding_months: number | null
  sku_count: number
  max_lead_time_days: number | null
}
