"""Property-based test for idempotent execution of both revenue solutions.

Covers Property 7 from the revenue-pipeline design document: running a solution
more than once produces an identical revenue table on the five reporting columns
(idempotent execution).

This is a single parametrised test that exercises BOTH solutions:

  * SQL_Solution (``sql/revenue.sql`` via :func:`sql_runner.run_sql_solution`),
    driven from ``product``/``sales`` TABLES seeded into a throwaway temp DB.
  * Python_Solution (``run_python.main``: extract -> transform -> load), driven
    from generated ``product.csv``/``sales.csv`` files into a fresh temp DB.

Each example generates a fresh ``product``/``sales`` dataset, deliberately
seeding:

  * duplicate natural keys with varying ``insert_timestamp_utc`` (exercises dedup),
  * ``orderdate_utc`` values spanning Dec 2024 .. Feb 2025 (exercises the
    January-2025 period filter, including both boundaries and out-of-range noise).

The bundled ``fw/product_sales.db`` and Source_CSV files are never touched — see
``tests/conftest.py``.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from run_python import main as run_python_main
from sql_runner import run_sql_solution

from tests.conftest import read_revenue_rows

# --------------------------------------------------------------------------- #
# Generators
# --------------------------------------------------------------------------- #

# Dates spanning a window around January 2025 so the period filter is exercised
# on both sides: Dec 2024 (excluded), all of Jan 2025 (included, with boundaries
# 2025-01-01 and 2025-01-31), and early Feb 2025 (excluded).
_WINDOW_START = date(2024, 12, 25)
_WINDOW_END = date(2025, 2, 5)
_WINDOW_DAYS = (_WINDOW_END - _WINDOW_START).days + 1

_order_dates = st.builds(
    lambda i: (_WINDOW_START + timedelta(days=i)).isoformat(),
    st.integers(min_value=0, max_value=_WINDOW_DAYS - 1),
)

_insert_timestamps = st.builds(
    lambda i: (date(2025, 1, 1) + timedelta(days=i)).isoformat() + "T00:00:00Z",
    st.integers(min_value=0, max_value=60),
)


@st.composite
def _datasets(draw):
    """Generate a (products, sales) pair.

    * 1-5 distinct SKUs with REAL prices.
    * 0-20 sales rows referencing those SKUs. Order ids are drawn from a small
      pool so the same natural key (sku_id, order_id, orderdate_utc) recurs with
      different ``insert_timestamp_utc`` values, exercising deduplication.
    """
    n_skus = draw(st.integers(min_value=1, max_value=5))
    sku_ids = list(range(1, n_skus + 1))

    products = []
    for sku_id in sku_ids:
        price = draw(st.floats(min_value=0.01, max_value=999.99,
                               allow_nan=False, allow_infinity=False))
        products.append((sku_id, f"sku-{sku_id}", round(price, 2),
                         "2024-12-01T00:00:00Z"))

    order_id_pool = ["o1", "o2", "o3"]
    n_sales = draw(st.integers(min_value=0, max_value=20))
    sales = []
    for _ in range(n_sales):
        sku_id = draw(st.sampled_from(sku_ids))
        order_id = draw(st.sampled_from(order_id_pool))
        qty = draw(st.integers(min_value=0, max_value=50))
        orderdate = draw(_order_dates)
        insert_ts = draw(_insert_timestamps)
        sales.append((sku_id, order_id, qty, orderdate, insert_ts))

    return products, sales


# --------------------------------------------------------------------------- #
# Property 7
# --------------------------------------------------------------------------- #

# Feature: revenue-pipeline, Property 7: Idempotent execution
@pytest.mark.parametrize("solution", ["sql", "python"])
@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=_datasets())
def test_solution_is_idempotent(solution, make_db, make_csvs, data):
    """Running a solution twice yields identical reporting columns.

    **Validates: Requirements 2.9**

    For both solutions we run the build twice against the same target database
    and assert the five reporting columns are byte-for-byte identical between
    runs (the DROP-then-CREATE rebuild makes re-runs safe).
    """
    products, sales = data

    if solution == "sql":
        # SQL_Solution reads the product/sales TABLES from the DB itself.
        db = make_db(products=products, sales=sales)

        run_sql_solution(db_path=db)
        first = read_revenue_rows(db)

        run_sql_solution(db_path=db)
        second = read_revenue_rows(db)
    else:
        # Python_Solution reads the generated CSVs and writes into a fresh,
        # empty target DB (seeded with no product/sales rows of its own).
        product_csv, sales_csv = make_csvs(products=products, sales=sales)
        db = make_db(products=[], sales=[])

        run_python_main(product_csv, sales_csv, db)
        first = read_revenue_rows(db)

        run_python_main(product_csv, sales_csv, db)
        second = read_revenue_rows(db)

    assert first == second
