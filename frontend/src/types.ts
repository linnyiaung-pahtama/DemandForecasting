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
  pg_sellable: number | null // null only in runs saved before stock came from the stock reports
  pdg_sellable: number | null
  pg_non_sellable: number | null
  pdg_non_sellable: number | null
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

export type StockSource = 'PG' | 'PDG'

export interface StockFileSummary {
  source: StockSource
  as_of: string | null
  skus_with_stock: number // Data SKUs with at least one line in this file
  sellable_cartons: number // summed over Data SKUs only
  non_sellable_cartons: number
}

export interface StockResult {
  pg: StockFileSummary
  pdg: StockFileSummary
  skus_with_stock: number // Data SKUs with a line in either file
  warnings: ParseWarning[] // report warnings (PG then PDG), then merge warnings
}

export interface InspectResponse {
  file_name: string
  sales_file_name: string
  pg_file_name: string
  pdg_file_name: string
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
  stock: StockResult
  warnings: ParseWarning[] // Data file, sales export, stock report and merge, then stock date warnings
}

export type SkuStatus = 'TO_ORDER' | 'NO_ORDER_NEEDED' | 'HOLDING_NOT_SET' | 'NO_DEMAND_DATA'

export interface DemandValue {
  month: string // "YYYY-MM"
  source: 'actual' | 'forecast'
  value: number | null
  valid: boolean
}

export interface MonthPlan {
  month: string // "YYYY-MM"
  opening: number
  demand: number
  order: number | null // null when holding is not set
  moq_applied: boolean
  closing: number
  order_month: boolean // false only for order-plan months between orders
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
  pg_sellable: number | null // breakdown of sellable; null in older runs
  pdg_sellable: number | null
  pg_non_sellable: number | null
  pdg_non_sellable: number | null
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
  monthly: MonthPlan[] | null // the 12-month plan; null for runs saved before it
  // The order plan (ordering every order_cycle_months) and its this-month values; the fields above are the
  // order demand forecast's. Null / false for runs saved before the order cycle setting.
  order_cycle_months: number | null
  order_plan: MonthPlan[] | null
  plan_order_up_to: number | null
  plan_required: number | null
  plan_order_qty: number | null
  plan_moq_applied: boolean
  plan_status: SkuStatus | null
}

export interface SupplierSettings {
  supplier: string
  holding_months: number | null
  moq: number | null // null only in runs saved before MOQ moved to supplier settings
  lead_time_days: number | null
  order_cycle_months: number | null // null only in runs saved before the order cycle setting
}

export type SettingField = 'holding_months' | 'moq' | 'lead_time_days' | 'order_cycle_months'

export interface SettingsLogEntry {
  id: number
  supplier: string
  field: SettingField
  old_value: number | null
  new_value: number | null
  changed_at: string
}

export interface HoldingPlan {
  plan_date: string
  actual_months: string[]
  forecast_months: string[] // the 3 used
  plan_months: string[] // the 12 months of the 12-month plan; empty for runs saved before it
  skus: SkuResult[]
  settings_used: SupplierSettings[]
  blocked_suppliers: string[]
  counts: Record<string, number> // TO_ORDER, NO_ORDER_NEEDED, HOLDING_NOT_SET, NO_DEMAND_DATA, ZERO_FORECAST
  plan_counts: Record<string, number> | null // the same keys by order-plan status; null for older runs
}

export interface RunListItem {
  id: number
  created_at: string
  file_name: string
  sales_file_name: string
  pg_file_name: string | null // null for runs saved before the stock reports
  pdg_file_name: string | null
  plan_date: string
  sku_count: number
}

export interface RunRecord extends RunListItem {
  parsed: ParsedInput
  actual: ActualSales
  result: HoldingPlan
  stock: StockResult | null // null for runs saved before the stock reports
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
  moq: number | null // from the plan's settings; null for runs saved before supplier MOQ/lead time
  lead_time_days: number | null
  monthly_order_qty: number[] | null // per plan month; null for runs saved before the 12-month plan
  twelve_month_total: number | null
  // The order plan's figures; null for older runs. Monthly totals are also null for a principal whose holding
  // is not set, and null in months that are not order months.
  order_cycle_months: number | null
  plan_skus_to_order: number | null
  plan_total_order_qty: number | null
  plan_monthly_order_qty: (number | null)[] | null
  plan_twelve_month_total: number | null
}

export interface SupplierSettingView {
  supplier: string
  holding_months: number | null
  moq: number
  lead_time_days: number | null
  order_cycle_months: number
  sku_count: number
}
