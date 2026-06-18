"""Property-based test for the reporting-period filter.

# Feature: revenue-pipeline, Property 2: Reporting-period filter admits exactly January 2025

Validates: Requirements 4.1, 4.2

For any generated ``sales`` table whose ``orderdate_utc`` values span
2024-12-25 .. 2025-02-05, only records dated within the inclusive January-2025
reporting period (2025-01-01 .. 2025-01-31) contribute to the ``revenue``
table. The boundary days 2025-01-01 and 2025-01-31 DO contribute; out-of-range
days such as 2024-12-31 and 2025-02-01 do NOT. We use unique natural keys so
deduplication is a no-op and the period filter is the only effect under test.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from revenue_pipeline.build_revenue import build_revenue

# Reporting period bounds (inclusive), matching the assignment's fixed January 2025.
PERIOD_START = date(2025, 1, 1)
PERIOD_END = date(2025, 1, 31)

# Full span of dates the generator may draw from: Dec 2024 .. early Feb 2025.
GEN_START = date(2024, 12, 25)
GEN_END = date(2025, 2, 5)
_SPAN_DAYS = (GEN_END - GEN_START).days

# Dates that MUST always appear in the generated data so the boundary and
# out-of-range behaviour is exercised on every example.
_FORCED_DATES = (
    date(2024, 12, 31),  # out of range (just before the period) -> excluded
    date(2025, 1, 1),    # lower boundary -> included
    date(2025, 1, 31),   # upper boundary -> included
    date(2025, 2, 1),    # out of range (just after the period) -> excluded
)


def _in_period(d: date) -> bool:
    return PERIOD_START <= d <= PERIOD_END


# A single sale draws an order date anywhere across the span, plus a sku, an
# order id and a positive quantity.
_order_dates = st.dates(min_value=GEN_START, max_value=GEN_END)
_sku_ids = st.integers(min_value=1, max_value=5)
_quantities = st.integers(min_value=1, max_value=100)


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(
    sku_ids=st.lists(_sku_ids, min_size=1, max_size=5, unique=True),
    sale_specs=st.lists(
        st.tuples(_sku_ids, _order_dates, _quantities),
        min_size=0,
        max_size=40,
    ),
    forced_sku=_sku_ids,
    forced_qty=_quantities,
)
def test_period_filter_admits_exactly_january_2025(
    make_db, revenue_reader, sku_ids, sale_specs, forced_sku, forced_qty
):
    # Ensure every sku referenced by sales also exists in product (so a LEFT
    # JOIN never drops a sale for an unknown sku and the per-cell comparison is
    # well-defined). Always include the forced sku too.
    referenced = set(sku_ids) | {s[0] for s in sale_specs} | {forced_sku}
    products = [
        (sku, f"sku-{sku}", 10.0, "2025-01-01T00:00:00Z") for sku in sorted(referenced)
    ]

    # Build sales rows with UNIQUE natural keys (sku_id, order_id, orderdate_utc)
    # so deduplication is a no-op and the period filter is the only effect.
    sales = []
    order_seq = 0

    def add_sale(sku: int, d: date, qty: int) -> None:
        nonlocal order_seq
        order_seq += 1
        sales.append(
            (sku, f"o{order_seq}", qty, d.isoformat(), "2025-01-01T00:00:00Z")
        )

    for sku, d, qty in sale_specs:
        add_sale(sku, d, qty)

    # Always exercise the two boundary days (included) and two adjacent
    # out-of-range days (excluded) for the forced sku.
    for d in _FORCED_DATES:
        add_sale(forced_sku, d, forced_qty)

    db = make_db(products=products, sales=sales)
    build_revenue(db_path=db)
    rows = revenue_reader(db)

    # --- Assertion 1: every date_id in the output lies within Jan 2025 -------- #
    # The revenue table is a fixed 31-day calendar, so no out-of-period date may
    # ever appear regardless of what dates the sales carried.
    out_dates = {date.fromisoformat(date_id) for (_sku, date_id, *_rest) in rows}
    assert out_dates, "revenue table unexpectedly empty"
    for d in out_dates:
        assert _in_period(d), f"out-of-period date leaked into revenue: {d}"
    assert min(out_dates) >= PERIOD_START
    assert max(out_dates) <= PERIOD_END
    # All 31 January days are present (dense calendar).
    expected_days = {
        PERIOD_START + timedelta(days=i)
        for i in range((PERIOD_END - PERIOD_START).days + 1)
    }
    assert out_dates == expected_days

    # --- Assertion 2: per-cell sales reflect ONLY in-period generated sales --- #
    # Expected sales per (sku, day) counts only rows whose orderdate is in range;
    # out-of-range rows must not leak into any in-period cell.
    expected = defaultdict(int)
    for sku, order_id, qty, orderdate_iso, _ts in sales:
        d = date.fromisoformat(orderdate_iso)
        if _in_period(d):
            expected[(str(sku), orderdate_iso)] += qty

    total_in_period = sum(expected.values())
    total_revenue_table_sales = 0
    for sku_id, date_id, _price, cell_sales, _revenue in rows:
        total_revenue_table_sales += cell_sales
        assert cell_sales == expected.get((sku_id, date_id), 0), (
            f"sales mismatch for ({sku_id}, {date_id}): "
            f"got {cell_sales}, expected {expected.get((sku_id, date_id), 0)}"
        )

    # Total sales in the revenue table equals the sum of in-period generated
    # sales: nothing from out-of-range dates leaked in, nothing in-period dropped.
    assert total_revenue_table_sales == total_in_period


@settings(max_examples=1, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(qty=st.just(7))
def test_boundary_dates_included_and_adjacent_excluded(make_db, revenue_reader, qty):
    """Explicit boundary check: 2025-01-01 and 2025-01-31 contribute;
    2024-12-31 and 2025-02-01 do not."""
    products = [(1, "sku-1", 10.0, "2025-01-01T00:00:00Z")]
    sales = [
        (1, "a", qty, "2024-12-31", "2025-01-01T00:00:00Z"),  # excluded
        (1, "b", qty, "2025-01-01", "2025-01-01T00:00:00Z"),  # included (lower bound)
        (1, "c", qty, "2025-01-31", "2025-01-01T00:00:00Z"),  # included (upper bound)
        (1, "d", qty, "2025-02-01", "2025-01-01T00:00:00Z"),  # excluded
    ]

    db = make_db(products=products, sales=sales)
    build_revenue(db_path=db)
    rows = revenue_reader(db)

    by_date = {date_id: cell_sales for (_sku, date_id, _p, cell_sales, _r) in rows}

    # Boundary days carry the sale quantity.
    assert by_date["2025-01-01"] == qty
    assert by_date["2025-01-31"] == qty

    # Out-of-range days never appear in the table at all.
    assert "2024-12-31" not in by_date
    assert "2025-02-01" not in by_date

    # Total over the whole table equals only the two in-period sales.
    assert sum(by_date.values()) == 2 * qty
