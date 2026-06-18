"""Property-based test for the deduplication step of the revenue pipeline.

# Feature: revenue-pipeline, Property 1: Deduplication keeps one latest row per natural key

Property 1 (design.md): For any generated ``sales`` table with arbitrary duplicate
natural keys ``(sku_id, order_id, orderdate_utc)`` and arbitrary
``insert_timestamp_utc`` values, the deduplication step retains exactly one row per
natural key — the row with the maximum ``insert_timestamp_utc``. Duplicates of the
same natural key collapse to a single logical sale (they are NOT summed); distinct
natural keys on the same (SKU, day) still sum together.

Validates: Requirements 3.1, 3.2
"""

from __future__ import annotations

import string
from datetime import datetime, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from revenue_pipeline.build_revenue import build_revenue

# Base instant used to turn an integer ordinal into a fixed-width ISO-8601 string.
# Fixed-width ISO timestamps sort lexically in chronological order, so the lexical
# MAX equals the latest insert — exactly the tiebreaker the dedup uses.
_TS_BASE = datetime(2020, 1, 1)


def _fmt_ts(ordinal: int) -> str:
    """Render an integer ordinal as a fixed-width ISO-8601 timestamp string."""
    return (_TS_BASE + timedelta(seconds=ordinal)).isoformat()


# An order_id alphabet kept simple/printable so generated natural keys stay readable.
_ORDER_ID = st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=5)


@st.composite
def dedup_scenarios(draw):
    """Generate a (products, sales, expected_per_cell) scenario.

    The scenario deliberately seeds each natural key with one OR MORE duplicate
    ingestions carrying distinct ``insert_timestamp_utc`` values and differing
    ``sales`` quantities, so the dedup logic has something to collapse.

    Returns:
        products: list of product rows for ``make_db``.
        sales_rows: flattened list of sales rows (all duplicates included).
        expected: dict mapping (sku_id_text, "YYYY-MM-DD") -> expected summed
            sales after dedup (sum of the max-timestamp quantity per natural key).
    """
    # 1..4 SKUs, each with a positive price.
    n_skus = draw(st.integers(min_value=1, max_value=4))
    sku_ids = list(range(1, n_skus + 1))
    prices = {
        sku: draw(st.floats(min_value=0.01, max_value=1000.0,
                            allow_nan=False, allow_infinity=False))
        for sku in sku_ids
    }
    products = [(sku, f"desc-{sku}", prices[sku], "2025-01-01T00:00:00") for sku in sku_ids]

    # Distinct natural keys: (sku_id, order_id, day-of-january). `unique=True` on the
    # tuple guarantees each (sku, order_id, day) is a genuinely distinct natural key.
    keys = draw(
        st.lists(
            st.tuples(
                st.sampled_from(sku_ids),
                _ORDER_ID,
                st.integers(min_value=1, max_value=31),
            ),
            min_size=1,
            max_size=12,
            unique=True,
        )
    )

    sales_rows: list[tuple] = []
    expected: dict[tuple[str, str], int] = {}

    for sku, order_id, day in keys:
        orderdate = f"2025-01-{day:02d}"

        # Per-key duplicate quantities (>=1 duplicate). Each duplicate gets a DISTINCT
        # timestamp ordinal so the latest ingestion is unambiguous.
        quantities = draw(st.lists(st.integers(min_value=0, max_value=500),
                                   min_size=1, max_size=4))
        ts_ordinals = draw(
            st.lists(st.integers(min_value=0, max_value=10**9),
                     min_size=len(quantities), max_size=len(quantities), unique=True)
        )

        # Emit one physical sales row per duplicate ingestion of this natural key.
        for qty, ts in zip(quantities, ts_ordinals):
            sales_rows.append((sku, order_id, qty, orderdate, _fmt_ts(ts)))

        # The retained row is the one with the MAX insert timestamp; its quantity is
        # what should contribute to the (sku, day) cell.
        latest_idx = max(range(len(ts_ordinals)), key=lambda i: ts_ordinals[i])
        retained_qty = quantities[latest_idx]

        cell = (str(sku), orderdate)
        expected[cell] = expected.get(cell, 0) + retained_qty

    return products, sales_rows, expected


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(dedup_scenarios())
def test_dedup_keeps_one_latest_row_per_natural_key(make_db, revenue_reader, scenario):
    """Each natural key collapses to its max-timestamp row before aggregation.

    The revenue cell for a (SKU, day) must equal the sum of the deduped (one per
    natural key, latest insert) quantities — never the summed-over-duplicates total.
    """
    products, sales_rows, expected = scenario

    db = make_db(products=products, sales=sales_rows)
    build_revenue(db_path=db)

    rows = revenue_reader(db)

    # Map the produced revenue table to per-cell sales for comparison.
    produced = {(sku_id, date_id): sales for (sku_id, date_id, _price, sales, _rev) in rows}

    # Every cell that should carry deduped sales matches the expected deduped sum.
    for cell, expected_sales in expected.items():
        assert produced.get(cell, 0) == expected_sales, (
            f"cell {cell}: expected deduped sales {expected_sales}, "
            f"got {produced.get(cell, 0)}"
        )

    # Every other (SKU, day) cell is zero-filled (no in-period sales contributed).
    for cell, sales in produced.items():
        if cell not in expected:
            assert sales == 0, f"cell {cell}: expected zero-fill, got {sales}"
