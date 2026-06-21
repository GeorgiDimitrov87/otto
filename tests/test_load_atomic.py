"""Atomic-rebuild guarantee for the Load_Module (criterion 4.5).

``write_revenue`` rebuilds the ``revenue`` table inside a single transaction:
``BEGIN`` + ``DROP TABLE IF EXISTS`` + explicit ``CREATE TABLE`` + bulk
``executemany`` insert, committed only on success and rolled back on any
failure. A reader must therefore observe either the *previous* table or the
*fully rebuilt* one — never a partial write.

This test exercises the rollback path on a hermetic temp database:

1. Build a valid ``revenue`` table from a first set of rows and capture its
   contents.
2. Issue a second ``write_revenue`` whose rows trigger a failure *mid
   transaction* — after the in-transaction ``DROP TABLE`` and ``CREATE TABLE``
   have already executed, during ``executemany``.
3. Assert the original table from step 1 survives unchanged, proving the
   DROP/CREATE/insert of the failed build was rolled back atomically.

The failure is injected by binding an unsupported Python value (a bare
``object()``) as a column value. ``write_revenue`` materialises the insert
tuples *before* opening the connection, so this value flows untouched into
``executemany`` and raises :class:`sqlite3.InterfaceError` only once the
transaction is already open and the previous table has been dropped — exactly
the window the atomicity guarantee must cover. Never touches
``fw/product_sales.db``.
"""

from __future__ import annotations

import sqlite3

import pytest

from load import write_revenue


def _read_back(db_path, table: str = "revenue") -> list[tuple]:
    """Return the five reporting columns ordered by (sku_id, date_id)."""
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            f"SELECT sku_id, date_id, price, sales, revenue "
            f"FROM {table} ORDER BY sku_id, date_id"
        )
        return cursor.fetchall()
    finally:
        conn.close()


def test_mid_load_failure_rolls_back_leaving_previous_table_intact(tmp_path):
    """A mid-transaction failure must leave the previous revenue table intact."""
    db_path = tmp_path / "atomic_revenue.db"

    # --- Step 1: build a valid revenue table and capture its contents. -------
    original_rows = [
        {"sku_id": "1", "date_id": "2025-01-01", "price": 9.99,
         "sales": 3, "revenue": 29.97},
        {"sku_id": "2", "date_id": "2025-01-02", "price": 4.50,
         "sales": 0, "revenue": 0.0},
    ]
    written = write_revenue(original_rows, db_path=db_path)
    assert written == len(original_rows)

    captured = _read_back(db_path)
    assert captured == [
        ("1", "2025-01-01", 9.99, 3, 29.97),
        ("2", "2025-01-02", 4.50, 0, 0.0),
    ]

    # --- Step 2: second build with NEW rows that fail mid-transaction. -------
    # The malformed row carries an unsupported binding value (a bare object),
    # which raises sqlite3.InterfaceError during executemany — AFTER the
    # in-transaction DROP TABLE + CREATE TABLE have already run.
    new_rows = [
        {"sku_id": "10", "date_id": "2025-01-10", "price": 1.0,
         "sales": 1, "revenue": 1.0},
        {"sku_id": "11", "date_id": "2025-01-11", "price": 2.0,
         "sales": 2, "revenue": object()},  # unsupported -> raises mid-load
    ]
    with pytest.raises((sqlite3.InterfaceError, sqlite3.ProgrammingError)):
        write_revenue(new_rows, db_path=db_path)

    # --- Step 3: the original table must be intact (no partial write). -------
    after_failure = _read_back(db_path)
    assert after_failure == captured, (
        "Rollback failed: the revenue table was modified by the aborted build"
    )
