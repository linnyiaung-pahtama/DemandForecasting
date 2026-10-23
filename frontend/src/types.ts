// Mirrors backend/app/models.py field-for-field. Dates are ISO strings (YYYY-MM-DD),
// datetimes are ISO date-time strings.

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

export interface SupplierSetting {
  supplier: string
  reorder_days: number
  target_days: number
  is_default: boolean
}

export type FlagCode =
  | 'ORDER_NOW'
  | 'STOCKOUT_RISK'
  | 'EXCESS'
  | 'EXPIRY_RISK'
  | 'NO_FORECAST_HOLDING_STOCK'
  | 'MTD_ABOVE_FORECAST'
  | 'LEAD_TIME_EXCEEDS_REORDER'
  | 'MOQ_EXCEEDS_SHELF_LIFE'
  | 'MISSING_LEAD_TIME'

export interface Flag {
  code: FlagCode
  message: string
}

export interface OrderReason {
  on_hand: number
  on_order: number
  inventory_position: number
  stock_at_arrival: number
  reorder_qty: number
  target_qty: number
  raw_qty: number
  moq_applied: boolean
  shelf_life_cap: number | null
  cap_applied: boolean
}

export interface PlannedOrder {
  order_date: string
  arrival_date: string
  qty: number
  reason: OrderReason
}

export interface WeekProjection {
  week: number // 1-based
  start: string
  end: string
  demand: number
  arrivals: number
  closing_stock: number
  lost: number
  reorder_qty: number // at week start
  target_qty: number // at week start
}

export interface SkuPlan {
  sap_code: string
  supplier: string
  description: string
  lead_time_days: number | null
  moq: number
  shelf_life_months: number | null
  sellable: number
  non_sellable: number
  sit: number
  starting_stock: number
  days_of_cover: number | null
  total_forecast: number
  orders: PlannedOrder[]
  weeks: WeekProjection[]
  flags: Flag[]
  stockout_days: number
  stockout_qty: number
  first_stockout_date: string | null
}

export interface SupplierSummary {
  supplier: string
  reorder_days: number
  target_days: number
  is_default: boolean
  sku_count: number
  skus_to_order: number
  cartons_in_window: number
  earliest_order_date: string | null // covers ALL of the supplier's orders
  flag_counts: Record<string, number>
  max_lead_time_days: number | null
}

export interface PlanResult {
  plan_date: string
  skus: SkuPlan[]
  settings_used: SupplierSetting[]
  new_suppliers: string[]
  flag_counts: Record<string, number>
}

export interface RunListItem {
  id: number
  created_at: string
  file_name: string
  plan_date: string
  sku_count: number
}

export interface RunRecord extends RunListItem {
  parsed: ParsedInput
  result: PlanResult
}

export interface SupplierSettingView extends SupplierSetting {
  max_lead_time_days: number | null
  sku_count: number
}

export interface InspectResponse {
  file_name: string
  sku_count: number
  supplier_count: number
  forecast_months: string[]
  mtd_label: string
  mtd_end: string
  default_plan_date: string
  min_plan_date: string
  max_plan_date: string
  warnings: ParseWarning[]
}
