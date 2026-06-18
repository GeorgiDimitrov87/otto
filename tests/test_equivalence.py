"""Property-based tests for SQL/Python equivalence and idempotency.

Covers two design properties from the revenue-pipeline design document:

  * Property 6 — the SQL_Solution (``sql/revenue.sql`` via ``run_sql_solution``)
    and the Python_Solution (``build_revenue``) produce identical revenue tables
    on the five reporting columns.
  * Property 7 — running a solution more than once produces identical revenue
    tables on the reporting columns (idempotent execution).

Each test generates a fresh ``product``/``sales`` dataset into a throwaway temp
SQLite database via the ``make_db`` fixture, deliberately seeding:

  * duplicate natural keys with varying ``insert_timestamp_utc`` (exercises dedup),
  * ``orderdate_utc`` values spanning Dec 2024 .. Feb 2025 (exercises the
    January-2025 period filter, including both boundaries and out-of-range noise).

The bundled ``fw/product_sales.db`` is never touched — see ``tests/conftest.py``.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from revenue_pipeline.build_revenue import build_revenue
from revenue_pipeline.sql_runner import run_sql_solution

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
# Property 6
# --------------------------------------------------------------------------- #

# Feature: revenue-pipeline, Property 6: SQL and Python solutions are equivalent
@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=_datasets())
def test_sql_and_python_solutions_are_equivalent(make_db, data):
    """SQL_Solution and Python_Solution agree on the reporting columns.

    **Validates: Requirements 7.3**

    Both solutions DROP and recreate ``revenue`` on the same database, so we run
    them sequentially on one temp DB and snapshot after each.
    """
    products, sales = data
    db = make_db(products=products, sales=sales)

    run_sql_solution(db_path=db)
    sql_rows = read_revenue_rows(db)

    build_revenue(db_path=db)
    python_rows = read_revenue_rows(db)

    assert len(sql_rows) == len(python_rows)
    for sql_row, py_row in zip(sql_rows, python_rows):
        sql_sku, sql_date, sql_price, sql_sales, sql_rev = sql_row
        py_sku, py_date, py_price, py_sales, py_rev = py_row
        assert sql_sku == py_sku
        assert sql_date == py_date
        assert sql_sales == py_sales
        assert sql_price == pytest.approx(py_price)
        assert sql_rev == pytest.approx(py_rev)


# --------------------------------------------------------------------------- #
# Property 7
# --------------------------------------------------------------------------- #

# Feature: revenue-pipeline, Property 7: Idempotent execution
@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=_datasets())
def test_python_solution_is_idempotent(make_db, data):
    """Running ``build_revenue`` twice yields identical reporting columns.

    **Validates: Requirements 8.1, 8.2**
    """
    products, sales = data
    db = make_db(products=products, sales=sales)

    build_revenue(db_path=db)
    first = read_revenue_rows(db)

    build_revenue(db_path=db)
    second = read_revenue_rows(db)

    assert first == second


# Feature: revenue-pipeline, Property 7: Idempotent execution
@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=_datasets())
def test_sql_solution_is_idempotent(make_db, data):
    """Running ``run_sql_solution`` twice yields identical reporting columns.

    **Validates: Requirements 8.1, 8.2**
    """
    products, sales = data
    db = make_db(products=products, sales=sales)

    run_sql_solution(db_path=db)
    first = read_revenue_rows(db)

    run_sql_solution(db_path=db)
    second = read_revenue_rows(db)

    assert first == second
