"""Daily demand series built from monthly forecast quantities."""
import calendar
from dataclasses import dataclass
from datetime import date

from app.models import SkuInput

EXTRA_COVER_DAYS = 3650


@dataclass
class DemandSeries:
    daily: list[float]  # index 0 = plan date
    tail_rate: float  # per-day demand beyond the horizon

    @property
    def horizon(self) -> int:
        return len(self.daily)

    def demand(self, day: int) -> float:
        return self.daily[day] if day < self.horizon else self.tail_rate

    def cover_qty(self, day: int, days: int) -> float:
        """Forecast demand over [day, day + days)."""
        return sum(self.demand(d) for d in range(day, day + days))

    def days_of_cover(self, day: int, qty: float) -> float | None:
        """Days until qty is used up starting at day (fractional in the last day).

        None if it is not used up within horizon + 3650 days.
        """
        if qty <= 0:
            return 0.0
        remaining = qty
        for d in range(day, self.horizon):
            dem = self.daily[d]
            if dem >= remaining:
                return (d - day) + remaining / dem
            remaining -= dem
        if self.tail_rate <= 0:
            return None
        start = max(day, self.horizon)
        end = start + remaining / self.tail_rate
        if end > self.horizon + EXTRA_COVER_DAYS:
            return None
        return end - day


def build_demand(sku: SkuInput, forecast_months: list[str], mtd_month: str,
                 plan_date: date) -> DemandSeries:
    daily: list[float] = []
    tail_rate = 0.0
    for month in forecast_months:
        year, mon = (int(p) for p in month.split("-"))
        days_in_month = calendar.monthrange(year, mon)[1]
        fc = sku.forecast.get(month, 0.0)
        tail_rate = fc / days_in_month
        if (year, mon) < (plan_date.year, plan_date.month):
            continue
        if (year, mon) == (plan_date.year, plan_date.month):
            first_day = plan_date.day
            n_days = days_in_month - first_day + 1
            if month == mtd_month:
                rate = max(fc - max(sku.mtd_sales, 0), 0) / n_days
            else:
                rate = tail_rate
        else:
            n_days = days_in_month
            rate = tail_rate
        daily.extend([rate] * n_days)
    return DemandSeries(daily=daily, tail_rate=tail_rate)
