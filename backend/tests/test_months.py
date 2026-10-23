from app.months import prev_months, next_months, month_label


def test_month_helpers():
    assert prev_months("2026-10", 3) == ["2026-07", "2026-08", "2026-09"]
    assert prev_months("2027-02", 3) == ["2026-11", "2026-12", "2027-01"]
    assert next_months("2026-11", 3) == ["2026-11", "2026-12", "2027-01"]
    assert month_label("2026-07") == "Jul 2026"
