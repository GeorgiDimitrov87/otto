"""Real-data smoke test for the revenue-pipeline (Requirements 5.4, 7.3).

This is the headline acceptance check: it runs BOTH solutions (SQL and Python)
against the *actual* bundled database ``fw/product_sales.db`` and asserts the two
properties that matter on real data:

  1. The ``revenue`` table has exactly 31,000 rows (1000 SKUs x 31 January days).
  2. The SQL output and the Python output are identical on the five reporting
     columns (sku_id, date_id, price, sales, revenue).

Unlike the hypothesis-driven property tests, this is a single example-based
integration test on the genuine assignment data.

Isolation: the original ``fw/product_sales.db`` is NEVER modified. The test copies
it to a throwaway location under pytest's ``tmp_path`` (with ``shutil.copy2`` to
preserve the file faithfully) and runs both solutions against the copy. If the
bundled DB is not present (e.g. a CI checkout without the data), the test is
skipped rather than failed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from revenue_pipeline.build_revenue import build_revenue
from revenue_pipeline.config import DB_PATH
from revenue_pipeline.sql_runner import run_sql_solution

# Expected dense grid: 1000 SKUs x 31 days of January 2025.
EXPECTED_ROW_COUNT = 31_000


@pytest.fixture
def real_db_copy(tmp_path) -> Path:
    """Copy the bundled ``fw/product_sales.db`` into ``tmp_path`` and return the copy.

    The original is left untouched; both solutions operate only on this copy.
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
    # --- SQL solution -----------------------------------------------------
    sql_row_count = run_sql_solution(db_path=real_db_copy)
    assert sql_row_count == EXPECTED_ROW_COUNT, (
        f"SQL solution wrote {sql_row_count} rows, expected {EXPECTED_ROW_COUNT}"
    )
    sql_rows = revenue_reader(real_db_copy)
    assert len(sql_rows) == EXPECTED_ROW_COUNT

    # --- Python solution (replaces the table in the same copy) ------------
    python_row_count = build_revenue(db_path=real_db_copy)
    assert python_row_count == EXPECTED_ROW_COUNT, (
        f"Python solution wrote {python_row_count} rows, expected {EXPECTED_ROW_COUNT}"
    )
    python_rows = revenue_reader(real_db_copy)
    assert len(python_rows) == EXPECTED_ROW_COUNT

    # --- Equivalence on the five reporting columns ------------------------
    # read_revenue_rows returns rows ordered by (sku_id, date_id), so the two
    # snapshots are directly comparable. Values should match exactly; the
    # technical insert_timestamp_utc build column is excluded by the reader.
    assert python_rows == sql_rows, (
        "SQL and Python outputs differ on the reporting columns"
    )
