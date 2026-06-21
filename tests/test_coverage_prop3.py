"""Property-based test for complete product-by-day coverage (Property 3).

# Feature: revenue-pipeline, Property 3: Complete product-by-day coverage with dynamic row count

Validates: Requirements 2.4, 2.10

For any generated ``products`` and ``sales`` data, the standard-library
:func:`transform.transform` produces exactly one row per ``(product, day)``
combination over the Reporting_Period calendar. The resulting row count equals
``product_count * days_in_reporting_period`` — where the day count is derived
**dynamically** from the period bounds rather than hard-coded to 31 — and the
set of ``(sku_id, date_id)`` pairs is exactly the full cartesian product, with
no missing and no duplicate pairs.

The transform is a pure function (row lists in, row list out), so the test
calls it directly on in-memory ``list[dict]`` inputs — no database is touched.
"""

from __future__ import annotations

from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from config import PERIOD_END, PERIOD_START
from transform import transform


# --------------------------------------------------------------------------- #
# Dynamically derived calendar (NOT hard-coded to 31).
# --------------------------------------------------------------------------- #
def _days_in_period(period_start: str, period_end: str) -> list[str]:
    """Return the inclusive ISO day list for the period, derived from the bounds."""
    start = date.fromisoformat(period_start)
    end = date.fromisoformat(period_end)
    return [
        (start + timedelta(days=i)).isoformat()
        for i in range((end - start).days + 1)
    ]


# In-period days plus a few just-outside boundary days, so generated sales
# exercise both in-grid lookups and the period filter while coverage is checked.
PERIOD_DAYS = _days_in_period(PERIOD_START, PERIOD_END)
OUT_OF_PERIOD_DAYS = ["2024-12-31", "2025-02-01", "2024-12-25", "2025-02-05"]
ALL_CANDIDATE_DAYS = PERIOD_DAYS + OUT_OF_PERIOD_DAYS


# --------------------------------------------------------------------------- #
# Generators
# --------------------------------------------------------------------------- #
# Small, unique SKU sets keep the dense grid cheap while still exercising the
# cartesian product across multiple products.
sku_ids = st.lists(
    st.integers(min_value=1, max_value=50),
    min_size=1,
    max_size=6,
    unique=True,
)

prices = st.floats(
    min_value=0.0,
    max_value=10_000.0,
    allow_nan=False,
    allow_infinity=False,
)

sales_quantities = st.integers(min_value=1, max_value=1000)


@st.composite
def products_and_sales(draw):
    """Generate ``(products, sales)`` as ``list[dict]`` for the transform.

    Sales rows get globally unique ``order_id`` values (so natural keys are
    unique and dedup is a no-op), land on a mix of in- and out-of-period days,
    and reference only generated SKUs. Some products are deliberately left with
    no sales so coverage/zero-fill still produces their full row set.
    """
    skus = draw(sku_ids)

    products = [
        {
            "sku_id": sku,
            "sku_description": f"sku-{sku}",
            "price": draw(prices),
            "insert_timestamp_utc": "2025-01-01T00:00:00Z",
        }
        for sku in skus
    ]

    sale_specs = draw(
        st.lists(
            st.tuples(
                st.sampled_from(skus),
                st.sampled_from(ALL_CANDIDATE_DAYS),
                sales_quantities,
            ),
            min_size=0,
            max_size=20,
        )
    )

    sales = [
        {
            "sku_id": sku,
            "order_id": f"order-{idx}",  # unique per row -> unique natural key
            "sales": qty,
            "orderdate_utc": day,
            "insert_timestamp_utc": "2025-01-10T00:00:00Z",
        }
        for idx, (sku, day, qty) in enumerate(sale_specs)
    ]

    return products, sales


# --------------------------------------------------------------------------- #
# Property 3: Complete product-by-day coverage with dynamic row count
# --------------------------------------------------------------------------- #
@settings(max_examples=100)
@given(data=products_and_sales())
def test_property_3_complete_coverage(data):
    """Output has one row per (product, day): count == products * days_in_period.

    Validates: Requirements 2.4, 2.10
    """
    products, sales = data

    rows = transform(products, sales, PERIOD_START, PERIOD_END)

    # Days derived dynamically from the period bounds — not hard-coded to 31.
    days = _days_in_period(PERIOD_START, PERIOD_END)
    distinct_skus = {p["sku_id"] for p in products}
    expected_count = len(distinct_skus) * len(days)

    # Row count equals product_count * days_in_period.
    assert len(rows) == expected_count

    # Exactly one row per (sku_id, date_id) — no duplicate pairs.
    pairs = [(r["sku_id"], r["date_id"]) for r in rows]
    assert len(pairs) == len(set(pairs)), "duplicate (sku_id, date_id) rows found"

    # The pair set is exactly the full product x day cartesian product:
    # no missing combinations and no extras.
    expected_pairs = {
        (str(sku), day) for sku in distinct_skus for day in days
    }
    assert set(pairs) == expected_pairs
