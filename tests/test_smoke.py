"""Real-data smoke test for the revenue-pipeline (Requirements 5.4, 2.11).

This is the headline acceptance check: it runs BOTH solutions (SQL and Python)
against the *actual* bundled assignment data and asserts the two properties that
matter on real data:

  1. The ``revenue`` table has exactly 31,000 rows (1000 SKUs x 31 January days).
  2. The SQL output and the Python output agree on the five reporting columns
     (sku_id, date_id, price, sales, revenue) — exact equality on
     ``sku_id``/``date_id``/``sales`` and ``abs=0.01`` tolerance on
     ``price``/``revenue``.

Unlike the hypothesis-driven property tests, this is a single example-based
integration test on the genuine assignment data.

Input sources and isolation
---------------------------
The two solutions read different real inputs and NEITHER bundled input is ever
modified:

  * The SQL_Solution reads the ``product``/``sales`` TABLES from the bundled
    ``fw/product_sales.db``. The test copies that DB into pytest's ``tmp_path``
    (with ``shutil.copy2`` to preserve it faithfully) and runs the SQL solution
    against the COPY, so the original DB is never written.
  * The Python_Solution reads the bundled ``fw/product.csv`` and ``fw/sales.csv``
    (``config.PRODUCT_CSV`` / ``config.SALES_CSV``) read-only and writes the
    ``revenue`` table into the SAME temp DB copy (it drops + recreates the
    table), so again only the throwaway copy is written.

If the bundled DB is not present (e.g. a CI checkout without the data), the test
is skipped rather than failed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from config import DB_PATH, PRODUCT_CSV, SALES_CSV
from run_python import main as run_python_solution
from sql_runner import run_sql_solution

# Expected dense grid: 1000 SKUs x 31 days of January 2025.
EXPECTED_ROW_COUNT = 31_000


@pytest.fixture
def real_db_copy(tmp_path) -> Path:
    """Copy the bundled ``fw/product_sales.db`` into ``tmp_path`` and return the copy.

    The original is left untouched; the SQL solution reads its ``product``/
    ``sales`` tables from this copy and the Python solution writes ``revenue``
    into it.
    """
    destination = tmp_path / "product_sales_smoke.db"
    shutil.copy2(DB_PATH, destination)
    return destination


@pytest.mark.skipif(
    not Path(DB_PATH).exists(),
    reason="bundled DB fw/product_sales.db not present",
)
def test_real_data_smoke(real_db_copy: Path, revenue_reader) -> None:
    """Both solutions build a 31,000-row table and agree on the reporting columns.

    ``revenue_reader`` is the conftest fixture wrapping ``read_revenue_rows``; it
    returns the five reporting columns ordered by (sku_id, date_id).
    """
    # --- SQL solution: reads product/sales tables from the DB copy --------
    sql_row_count = run_sql_solution(db_path=real_db_copy)
    assert sql_row_count == EXPECTED_ROW_COUNT, (
        f"SQL solution wrote {sql_row_count} rows, expected {EXPECTED_ROW_COUNT}"
    )
    sql_rows = revenue_reader(real_db_copy)
    assert len(sql_rows) == EXPECTED_ROW_COUNT

    # --- Python solution: reads the bundled CSVs, writes into the DB copy --
    python_row_count = run_python_solution(
        product_csv=PRODUCT_CSV,
        sales_csv=SALES_CSV,
        db_path=real_db_copy,
    )
    assert python_row_count == EXPECTED_ROW_COUNT, (
        f"Python solution wrote {python_row_count} rows, expected {EXPECTED_ROW_COUNT}"
    )
    python_rows = revenue_reader(real_db_copy)
    assert len(python_rows) == EXPECTED_ROW_COUNT

    # --- Equivalence on the five reporting columns ------------------------
    # read_revenue_rows returns rows ordered by (sku_id, date_id), so the two
    # snapshots are directly comparable: exact on sku_id/date_id/sales, within
    # abs=0.01 on price/revenue. The technical insert_timestamp_utc build column
    # is excluded by the reader.
    assert len(python_rows) == len(sql_rows)
    for sql_row, py_row in zip(sql_rows, python_rows):
        sql_sku, sql_date, sql_price, sql_sales, sql_rev = sql_row
        py_sku, py_date, py_price, py_sales, py_rev = py_row
        assert sql_sku == py_sku
        assert sql_date == py_date
        assert sql_sales == py_sales
        assert sql_price == pytest.approx(py_price, abs=0.01)
        assert sql_rev == pytest.approx(py_rev, abs=0.01)
