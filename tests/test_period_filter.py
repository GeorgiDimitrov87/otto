"""Property-based test for the reporting-period filter.

# Feature: revenue-pipeline, Property 2: Period filter admits exactly January 2025

Validates: Requirements 2.4

For any generated ``sales`` data whose ``orderdate_utc`` values span before,
within, and after the Reporting_Period (2024-12-25 .. 2025-02-05), only records
dated within the inclusive January-2025 reporting period (2025-01-01 ..
2025-01-31) contribute to the output ``revenue`` rows. The boundary days
2025-01-01 and 2025-01-31 DO contribute; out-of-range days such as 2024-12-31
and 2025-02-01 do NOT. Every example forces both boundary days (included) and
both adjacent out-of-range days (excluded), so the merged boundary check is
exercised on every run.

This test drives the pure :func:`transform` function directly on in-memory
``list[dict]`` inputs — no database, no Airflow. We use unique natural keys so
deduplication is a no-op and the period filter is the only effect under test.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from transform import transform

# Reporting period bounds (inclusive), matching the assignment's fixed January 2025.
PERIOD_START = date(2025, 1, 1)
PERIOD_END = date(2025, 1, 31)

# Full span of dates the generator may draw from: Dec 2024 .. early Feb 2025.
GEN_START = date(2024, 12, 25)
GEN_END = date(2025, 2, 5)

# Dates that MUST always appear in the generated data so the boundary and
# out-of-range behaviour is exercised on every example. This merges the old
# standalone boundary example into the property's generators.
_FORCED_DATES = (
    date(2024, 12, 31),  # out of range (just before the period) -> excluded
    date(2025, 1, 1),    # lower boundary -> included
    date(2025, 1, 31),   # upper boundary -> included
    date(2025, 2, 1),    # out of range (just after the period) -> excluded
)


def _in_period(d: date) -> bool:
    return PERIOD_START <= d <= PERIOD_END


# A single sale draws an order date anywhere across the span, plus a sku id and
# a positive quantity.
_order_dates = st.dates(min_value=GEN_START, max_value=GEN_END)
_sku_ids = st.integers(min_value=1, max_value=5)
_quantities = st.integers(min_value=1, max_value=100)


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
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
    sku_ids, sale_specs, forced_sku, forced_qty
):
    # Ensure every sku referenced by sales also exists in products so a missing
    # product never silently drops a sale and the per-cell comparison is
    # well-defined. Always include the forced sku too.
    referenced = set(sku_ids) | {s[0] for s in sale_specs} | {forced_sku}
    products = [
        {
            "sku_id": sku,
            "sku_description": f"sku-{sku}",
            "price": 10.0,
            "insert_timestamp_utc": "2025-01-01T00:00:00Z",
        }
        for sku in sorted(referenced)
    ]

    # Build sales rows with UNIQUE natural keys (sku_id, order_id, orderdate_utc)
    # so deduplication is a no-op and the period filter is the only effect.
    sales: list[dict] = []
    order_seq = 0

    def add_sale(sku: int, d: date, qty: int) -> None:
        nonlocal order_seq
        order_seq += 1
        sales.append(
            {
                "sku_id": sku,
                "order_id": f"o{order_seq}",
                "sales": qty,
                "orderdate_utc": d.isoformat(),
                "insert_timestamp_utc": "2025-01-01T00:00:00Z",
            }
        )

    for sku, d, qty in sale_specs:
        add_sale(sku, d, qty)

    # Always exercise the two boundary days (included) and two adjacent
    # out-of-range days (excluded) for the forced sku (merged boundary check).
    for d in _FORCED_DATES:
        add_sale(forced_sku, d, forced_qty)

    rows = transform(products, sales)

    # --- Assertion 1: every date_id in the output lies within Jan 2025 -------- #
    # The output is a fixed 31-day calendar, so no out-of-period date may ever
    # appear regardless of what dates the sales carried.
    out_dates = {date.fromisoformat(row["date_id"]) for row in rows}
    assert out_dates, "revenue output unexpectedly empty"
    for d in out_dates:
        assert _in_period(d), f"out-of-period date leaked into output: {d}"
    assert min(out_dates) >= PERIOD_START
    assert max(out_dates) <= PERIOD_END
    # All 31 January days are present (dense calendar).
    expected_days = {
        PERIOD_START + timedelta(days=i)
        for i in range((PERIOD_END - PERIOD_START).days + 1)
    }
    assert len(expected_days) == 31
    assert out_dates == expected_days

    # --- Assertion 2: per-cell sales reflect ONLY in-period generated sales --- #
    # Expected sales per (sku, day) counts only rows whose orderdate is in range;
    # out-of-range rows must not leak into any in-period cell.
    expected = defaultdict(int)
    for sale in sales:
        d = date.fromisoformat(sale["orderdate_utc"])
        if _in_period(d):
            expected[(str(sale["sku_id"]), sale["orderdate_utc"])] += sale["sales"]

    total_in_period = sum(expected.values())
    total_output_sales = 0
    for row in rows:
        total_output_sales += row["sales"]
        key = (row["sku_id"], row["date_id"])
        assert row["sales"] == expected.get(key, 0), (
            f"sales mismatch for {key}: "
            f"got {row['sales']}, expected {expected.get(key, 0)}"
        )

    # Total output sales equals the sum of in-period generated sales: nothing
    # from out-of-range dates leaked in, nothing in-period was dropped.
    assert total_output_sales == total_in_period

    # --- Boundary spot-check (merged from the old standalone example) --------- #
    # The forced boundary days carry the forced quantity for the forced sku;
    # the forced out-of-range days never appear as a non-zero cell.
    forced_cells = {(row["sku_id"], row["date_id"]): row["sales"] for row in rows}
    assert forced_cells[(str(forced_sku), "2025-01-01")] >= forced_qty
    assert forced_cells[(str(forced_sku), "2025-01-31")] >= forced_qty
    assert date(2024, 12, 31) not in out_dates
    assert date(2025, 2, 1) not in out_dates
