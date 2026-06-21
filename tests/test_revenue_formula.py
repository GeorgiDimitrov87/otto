"""Property-based test for the revenue-pipeline revenue formula.

# Feature: revenue-pipeline, Property 5: Revenue equals price times sales, with price drawn from product

For any output row produced by :func:`transform.transform`, ``price`` equals the
corresponding SKU's price from the ``product`` source and ``revenue == price * sales``.

This test exercises the pure standard-library :func:`transform.transform` directly on
in-memory ``product``/``sales`` dict lists — no database and no fixtures — so the
multiplicative formula is observed straight from the returned revenue rows.

Validates: Requirements 2.4
"""

from __future__ import annotations

import math

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from transform import transform

# January 2025 reporting period. Sales are generated within this window so that some
# (SKU, day) cells are non-zero, exercising the multiplicative branch of the formula.
_PERIOD_DAYS = [f"2025-01-{day:02d}" for day in range(1, 32)]


# Realistic REAL prices: whole numbers or up to two decimals, bounded to keep float
# arithmetic well-behaved and avoid spurious precision noise.
_prices = st.one_of(
    st.integers(min_value=0, max_value=100_000).map(float),
    st.integers(min_value=0, max_value=10_000_000).map(lambda cents: cents / 100.0),
)

# A set of products with distinct sku_ids and varied prices.
_products = st.lists(
    st.tuples(
        st.integers(min_value=1, max_value=50),  # sku_id (deduped below)
        _prices,
    ),
    min_size=1,
    max_size=8,
    unique_by=lambda t: t[0],
)


@st.composite
def _product_and_sales(draw):
    """Generate a product table and some in-period sales for those SKUs."""
    products = draw(_products)
    sku_ids = [sku_id for sku_id, _ in products]

    product_rows = [
        {
            "sku_id": sku_id,
            "sku_description": f"sku-{sku_id}",
            "price": price,
            "insert_timestamp_utc": "2024-12-01T00:00:00Z",
        }
        for sku_id, price in products
    ]

    sales_specs = draw(
        st.lists(
            st.tuples(
                st.sampled_from(sku_ids),                    # sku_id
                st.integers(min_value=1, max_value=10),      # order_id seed
                st.integers(min_value=1, max_value=20),      # sales quantity
                st.sampled_from(_PERIOD_DAYS),               # orderdate_utc (in period)
            ),
            max_size=30,
        )
    )
    sales_rows = [
        {
            "sku_id": sku_id,
            "order_id": f"o{order_seed}-{day}",
            "sales": qty,
            "orderdate_utc": day,
            "insert_timestamp_utc": "2025-01-15T00:00:00Z",
        }
        for sku_id, order_seed, qty, day in sales_specs
    ]

    return product_rows, sales_rows


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(data=_product_and_sales())
def test_revenue_equals_price_times_sales(data):
    """price matches the SKU's product price and revenue == price * sales for every row."""
    product_rows, sales_rows = data

    # sku_id is emitted as TEXT in the output, so map prices by the textual form.
    price_by_sku = {str(row["sku_id"]): row["price"] for row in product_rows}

    rows = transform(product_rows, sales_rows)
    assert rows, "expected the revenue output to contain rows"

    for row in rows:
        sku_id = row["sku_id"]
        price = row["price"]
        sales = row["sales"]
        revenue = row["revenue"]

        # price is drawn from the corresponding product row (Req 2.4).
        expected_price = price_by_sku[sku_id]
        assert math.isclose(price, expected_price, rel_tol=1e-9, abs_tol=1e-9), (
            f"price {price} != product price {expected_price} for sku {sku_id}"
        )

        # revenue == price * sales (Req 2.4). Use the same arithmetic as the
        # transform, compared with a tolerance to absorb any float representation noise.
        assert math.isclose(
            revenue, price * sales, rel_tol=1e-9, abs_tol=1e-9
        ), f"revenue {revenue} != price*sales {price * sales} for sku {sku_id}"
