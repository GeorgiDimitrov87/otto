"""Property-based test for the aggregation and zero-fill step of the revenue pipeline.

# Feature: revenue-pipeline, Property 4: Aggregation and zero-fill

Property 4 (design.md): For any generated ``product``/``sales`` data, each output cell's
``sales`` equals the sum of the deduplicated, in-period sales for that SKU and day, and
is exactly ``0`` for any ``(product, day)`` with no contributing sales.

This test exercises the pure standard-library :func:`transform.transform` directly on
in-memory ``product``/``sales`` dict lists — no database and no fixtures. Natural keys
``(sku_id, order_id, orderdate_utc)`` are made unique so deduplication is a no-op,
isolating the aggregation (SUM per SKU/day) and zero-fill behaviour under test.

Validates: Requirements 2.4
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from config import PERIOD_END, PERIOD_START
from transform import transform

# --------------------------------------------------------------------------- #
# Shared constants / helpers
# --------------------------------------------------------------------------- #

_START = date.fromisoformat(PERIOD_START)
_END = date.fromisoformat(PERIOD_END)
_N_DAYS = (_END - _START).days + 1  # 31 for January 2025
JANUARY_DAYS = [(_START + timedelta(days=i)).isoformat() for i in range(_N_DAYS)]

# In-period days plus just-outside boundary days, so generated sales exercise
# BOTH the period filter (out-of-period rows must not contribute) and zero-fill
# (in-period days with no sales must be exactly 0).
OUT_OF_PERIOD_DAYS = ["2024-12-25", "2024-12-31", "2025-02-01", "2025-02-05"]
ALL_CANDIDATE_DAYS = JANUARY_DAYS + OUT_OF_PERIOD_DAYS


def _is_in_period(date_id: str) -> bool:
    return PERIOD_START <= date_id <= PERIOD_END


# --------------------------------------------------------------------------- #
# Generators
# --------------------------------------------------------------------------- #

# Small SKU sets (1–5) keep the dense 31-day grid cheap while still exercising
# the cartesian product across multiple SKUs.
_sku_ids = st.lists(
    st.integers(min_value=1, max_value=50),
    min_size=1,
    max_size=5,
    unique=True,
)

_prices = st.floats(
    min_value=0.0,
    max_value=10_000.0,
    allow_nan=False,
    allow_infinity=False,
)

_quantities = st.integers(min_value=1, max_value=1000)


@st.composite
def products_and_sales(draw):
    """Generate a (products, sales) bundle of dict lists with UNIQUE natural keys.

    Each sales row receives a globally-unique ``order_id`` so natural keys
    ``(sku_id, order_id, orderdate_utc)`` are always distinct — deduplication is
    therefore a no-op and aggregation is the only effect under test. Multiple
    distinct orders may still land on the same (SKU, day), exercising SUM
    aggregation; many (SKU, day) cells are deliberately left without any sales to
    exercise zero-fill.
    """
    skus = draw(_sku_ids)

    price_by_sku = {sku: draw(_prices) for sku in skus}
    products = [
        {
            "sku_id": sku,
            "sku_description": f"sku-{sku}",
            "price": price_by_sku[sku],
            "insert_timestamp_utc": "2025-01-01T00:00:00Z",
        }
        for sku in skus
    ]

    sale_specs = draw(
        st.lists(
            st.tuples(
                st.sampled_from(skus),
                st.sampled_from(ALL_CANDIDATE_DAYS),
                _quantities,
            ),
            min_size=0,
            max_size=20,
        )
    )

    sales = []
    for idx, (sku, day, qty) in enumerate(sale_specs):
        sales.append(
            {
                "sku_id": sku,
                "order_id": f"order-{idx}",  # unique per row -> unique natural key
                "sales": qty,
                "orderdate_utc": day,
                "insert_timestamp_utc": "2025-01-10T00:00:00Z",
            }
        )

    return products, sales


# --------------------------------------------------------------------------- #
# Property 4: Aggregation and zero-fill
# --------------------------------------------------------------------------- #
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(data=products_and_sales())
def test_property_4_aggregation_and_zero_fill(data):
    """Each cell's sales == sum of in-period sales for that SKU/day, else exactly 0.

    Validates: Requirements 2.4
    """
    products, sales = data

    rows = transform(products, sales)

    # Expected per-(sku, day) sum, computed independently in Python. Natural keys
    # are unique so dedup is a no-op; only in-period sales contribute.
    expected = defaultdict(int)
    for sale in sales:
        if _is_in_period(sale["orderdate_utc"]):
            expected[(str(sale["sku_id"]), sale["orderdate_utc"])] += sale["sales"]

    # Aggregation: every output cell equals its expected summed (or zero) value.
    cells_with_sales = set(expected)
    for row in rows:
        cell = (row["sku_id"], row["date_id"])
        assert row["sales"] == expected.get(cell, 0), (
            f"sku={row['sku_id']} day={row['date_id']}: "
            f"got {row['sales']}, expected {expected.get(cell, 0)}"
        )

    # Zero-fill: every (product, day) cell with no contributing in-period sales is
    # present in the output and carries exactly 0.
    for row in rows:
        cell = (row["sku_id"], row["date_id"])
        if cell not in cells_with_sales:
            assert row["sales"] == 0, (
                f"sku={row['sku_id']} day={row['date_id']}: "
                f"expected zero-fill, got {row['sales']}"
            )
