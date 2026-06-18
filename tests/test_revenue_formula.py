"""Property-based test for the revenue-pipeline revenue formula.

# Feature: revenue-pipeline, Property 5: Revenue equals price times sales, with price drawn from product

For any Revenue_Table row, ``price`` equals the corresponding SKU's price from the
``product`` table and ``revenue == price * sales``.

**Validates: Requirements 6.2, 6.3**
"""

from __future__ import annotations

import math

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from revenue_pipeline.build_revenue import build_revenue

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
        (sku_id, f"sku-{sku_id}", price, "2024-12-01T00:00:00Z")
        for sku_id, price in products
    ]

    sales_rows = draw(
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
    sales_table = [
        (sku_id, f"o{order_seed}", qty, day, "2025-01-15T00:00:00Z")
        for sku_id, order_seed, qty, day in sales_rows
    ]

    return product_rows, sales_table


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=_product_and_sales())
def test_revenue_equals_price_times_sales(make_db, revenue_reader, data):
    """price matches the SKU's product price and revenue == price * sales for every row."""
    product_rows, sales_table = data

    # sku_id is emitted as TEXT in the output, so map by the textual form.
    price_by_sku = {str(sku_id): price for sku_id, _desc, price, _ts in product_rows}

    db = make_db(products=product_rows, sales=sales_table)
    build_revenue(db_path=db)

    rows = revenue_reader(db)
    assert rows, "expected the revenue table to contain rows"

    for sku_id, _date_id, price, sales, revenue in rows:
        # price is drawn from the corresponding product row (Req 6.2).
        expected_price = price_by_sku[sku_id]
        assert math.isclose(price, expected_price, rel_tol=1e-9, abs_tol=1e-9), (
            f"price {price} != product price {expected_price} for sku {sku_id}"
        )

        # revenue == price * sales (Req 6.3). Use the same arithmetic as the table,
        # compared with a tolerance to absorb any float representation noise.
        assert math.isclose(
            revenue, price * sales, rel_tol=1e-9, abs_tol=1e-9
        ), f"revenue {revenue} != price*sales {price * sales} for sku {sku_id}"
