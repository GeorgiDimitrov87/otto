"""CSV-missing edge-case test for the extract step (Requirement 2.16).

Requirement 2.16: *If a Source_CSV file is missing or cannot be read, then the
Python_Solution shall terminate with a descriptive error that names the missing
or unreadable file, without creating or partially writing the Revenue_Table.*

These tests point ``extract`` (and its ``read_products`` / ``read_sales``
helpers) at a path that does not exist and assert two things:

1. A descriptive ``FileNotFoundError`` is raised whose message *names the
   offending file* (so a reviewer can see which input was missing).
2. No ``revenue`` table is created or partially written. Because the missing
   file is detected during extract — before any database is opened — a fresh,
   hermetic temporary database file is never even created. We assert this on a
   throwaway ``tmp_path`` DB and never touch the bundled ``fw/product_sales.db``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

# ``conftest.py`` puts <repo>/src on sys.path, so the flat extract module is
# importable directly (it does ``from config import ...`` internally).
from extract import extract, read_products, read_sales


def _table_exists(db_path: Path, table: str = "revenue") -> bool:
    """Return True iff ``table`` exists in the SQLite database at ``db_path``."""
    if not db_path.exists():
        return False
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        return cursor.fetchone() is not None
    finally:
        conn.close()


def test_extract_missing_product_csv_raises_file_naming_error(tmp_path):
    """Missing product CSV -> FileNotFoundError naming that file; no revenue table."""
    missing_product = tmp_path / "does_not_exist_product.csv"
    # A real, present sales file would still never be reached: extract reads
    # products first. Use a path that genuinely does not exist.
    some_sales = tmp_path / "irrelevant_sales.csv"

    # Hermetic throwaway DB target; it must never be created by a failed extract.
    db_path = tmp_path / "revenue_missing_test.db"
    assert not db_path.exists()

    with pytest.raises(FileNotFoundError) as excinfo:
        extract(product_csv=missing_product, sales_csv=some_sales)

    # The error message must name the offending file.
    assert str(missing_product) in str(excinfo.value), (
        "FileNotFoundError should name the missing product CSV"
    )

    # No revenue table was created or partially written: extract fails before
    # any DB is opened, so the temp DB file does not even exist.
    assert not db_path.exists()
    assert not _table_exists(db_path, "revenue")


def test_extract_missing_sales_csv_raises_file_naming_error(tmp_path):
    """Missing sales CSV -> FileNotFoundError naming that file; no revenue table."""
    # Provide a valid product CSV so extract gets past read_products and fails
    # specifically on the missing sales file.
    product_csv = tmp_path / "product.csv"
    product_csv.write_text(
        "sku_id,sku_description,price,insert_timestamp_utc\n"
        "1,widget,9.99,2025-01-01T00:00:00Z\n",
        encoding="utf-8",
    )
    missing_sales = tmp_path / "does_not_exist_sales.csv"

    db_path = tmp_path / "revenue_missing_test.db"
    assert not db_path.exists()

    with pytest.raises(FileNotFoundError) as excinfo:
        extract(product_csv=product_csv, sales_csv=missing_sales)

    assert str(missing_sales) in str(excinfo.value), (
        "FileNotFoundError should name the missing sales CSV"
    )

    assert not db_path.exists()
    assert not _table_exists(db_path, "revenue")


def test_read_products_missing_path_names_file(tmp_path):
    """read_products on a missing path raises FileNotFoundError naming the file."""
    missing = tmp_path / "nope_product.csv"
    with pytest.raises(FileNotFoundError) as excinfo:
        read_products(missing)
    assert str(missing) in str(excinfo.value)


def test_read_sales_missing_path_names_file(tmp_path):
    """read_sales on a missing path raises FileNotFoundError naming the file."""
    missing = tmp_path / "nope_sales.csv"
    with pytest.raises(FileNotFoundError) as excinfo:
        read_sales(missing)
    assert str(missing) in str(excinfo.value)
