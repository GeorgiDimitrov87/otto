"""Config-validation test (Requirements 6.6, 6.7).

Before the rest of the suite runs, this fast, read-only test asserts that the
pipeline's configuration parameters match the bundled Source_DB / Source_CSV
data specifications, so a drift between config and data is caught immediately
rather than surfacing as a confusing downstream failure.

The bundled data is **1000 products × 31 January days = 31,000 rows**. This test
checks that:

  * the period bounds are exactly January 2025 (inclusive),
  * the period spans 31 days,
  * ``SQLITE_TIMEOUT`` is a positive number (the lock hang-guard),
  * the bundled ``fw/product.csv`` contains exactly 1000 product rows, and
  * the headline smoke-test expected row count (31,000) equals
    ``product_count (1000) × days_in_period (31)``.

It is strictly read-only on the bundled assets: it counts data rows in
``fw/product.csv`` without modifying it and never touches ``fw/product_sales.db``.
"""

from __future__ import annotations

import csv
from datetime import date

import config

# Bundled-data specifications (Req 6.3): 1000 SKUs × 31 January days.
EXPECTED_PRODUCT_COUNT = 1000
EXPECTED_DAYS_IN_PERIOD = 31
EXPECTED_ROW_COUNT = 31_000


def _days_in_period(start: str, end: str) -> int:
    """Inclusive day count between two ISO ``YYYY-MM-DD`` date strings."""
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    return (end_date - start_date).days + 1


def _count_csv_data_rows(path) -> int:
    """Count data rows (excluding the header) in a CSV file, read-only."""
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        next(reader, None)  # skip header
        return sum(1 for _ in reader)


def test_period_bounds_are_january_2025() -> None:
    """The configured reporting period is exactly January 2025, both bounds inclusive."""
    assert config.PERIOD_START == "2025-01-01"
    assert config.PERIOD_END == "2025-01-31"


def test_period_spans_thirty_one_days() -> None:
    """The inclusive January 2025 period spans 31 days."""
    assert _days_in_period(config.PERIOD_START, config.PERIOD_END) == EXPECTED_DAYS_IN_PERIOD


def test_sqlite_timeout_is_positive() -> None:
    """The SQLite connection timeout (lock hang-guard) is a positive number."""
    assert isinstance(config.SQLITE_TIMEOUT, (int, float))
    assert not isinstance(config.SQLITE_TIMEOUT, bool)
    assert config.SQLITE_TIMEOUT > 0


def test_bundled_product_csv_has_expected_product_count() -> None:
    """The bundled fw/product.csv contains exactly 1000 product rows (read-only)."""
    product_count = _count_csv_data_rows(config.PRODUCT_CSV)
    assert product_count == EXPECTED_PRODUCT_COUNT


def test_expected_row_count_equals_products_times_days() -> None:
    """The smoke-test expected row count equals product_count × days_in_period.

    31,000 == 1000 products × 31 January days. This ties the configuration and
    the bundled data together so the headline acceptance number is never a
    hard-coded magic value that can silently drift from the inputs.
    """
    product_count = _count_csv_data_rows(config.PRODUCT_CSV)
    days_in_period = _days_in_period(config.PERIOD_START, config.PERIOD_END)
    assert EXPECTED_ROW_COUNT == product_count * days_in_period
    assert product_count == EXPECTED_PRODUCT_COUNT
    assert days_in_period == EXPECTED_DAYS_IN_PERIOD
