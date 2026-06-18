"""Shared pytest fixtures for the revenue-pipeline test suite.

These fixtures build fresh, hermetic temporary SQLite databases seeded with
caller-provided ``product`` and ``sales`` rows. They NEVER touch the bundled
``fw/product_sales.db`` — every test (including the hypothesis-driven property
tests) gets its own throwaway database file under pytest's ``tmp_path``.

The module also puts the ``src/`` directory on ``sys.path`` so the package can
be imported as ``revenue_pipeline.*`` without installation:

    from revenue_pipeline.config import DB_PATH, REVENUE_TABLE
    from revenue_pipeline.sql_runner import run_sql_solution
    from revenue_pipeline.build_revenue import build_revenue
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Callable, Iterable, Sequence

import pytest

# --------------------------------------------------------------------------- #
# Make the src/ layout importable: insert <repo>/src at the front of sys.path
# so ``import revenue_pipeline`` resolves during test collection.
# --------------------------------------------------------------------------- #
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


# --------------------------------------------------------------------------- #
# Source-schema DDL. These mirror the bundled fw/product_sales.db schema:
#   product(sku_id INTEGER, sku_description TEXT, price REAL, insert_timestamp_utc TEXT)
#   sales(sku_id INTEGER, order_id TEXT, sales INTEGER, orderdate_utc TEXT,
#         insert_timestamp_utc TEXT)
# Column order matches the tuple order the seed helpers expect.
# --------------------------------------------------------------------------- #
_PRODUCT_DDL = """
CREATE TABLE product (
    sku_id               INTEGER,
    sku_description      TEXT,
    price                REAL,
    insert_timestamp_utc TEXT
)
"""

_SALES_DDL = """
CREATE TABLE sales (
    sku_id               INTEGER,
    order_id             TEXT,
    sales                INTEGER,
    orderdate_utc        TEXT,
    insert_timestamp_utc TEXT
)
"""

# Column tuples documenting the expected order of each seed row.
PRODUCT_COLUMNS = ("sku_id", "sku_description", "price", "insert_timestamp_utc")
SALES_COLUMNS = ("sku_id", "order_id", "sales", "orderdate_utc", "insert_timestamp_utc")

# The five reporting columns of the output ``revenue`` table, in canonical order.
REVENUE_REPORTING_COLUMNS = ("sku_id", "date_id", "price", "sales", "revenue")


def _seed_database(db_path: Path,
                   products: Iterable[Sequence],
                   sales: Iterable[Sequence]) -> Path:
    """Create ``product`` and ``sales`` tables at ``db_path`` and populate them.

    Args:
        db_path: Destination SQLite file (created fresh; any existing file is
            replaced so each call is hermetic).
        products: Iterable of ``(sku_id, sku_description, price,
            insert_timestamp_utc)`` rows.
        sales: Iterable of ``(sku_id, order_id, sales, orderdate_utc,
            insert_timestamp_utc)`` rows.

    Returns:
        The path to the seeded database (same as ``db_path``).
    """
    # Start from a clean slate so repeated factory calls never accumulate state.
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(_PRODUCT_DDL)
        conn.execute(_SALES_DDL)
        conn.executemany(
            "INSERT INTO product "
            "(sku_id, sku_description, price, insert_timestamp_utc) "
            "VALUES (?, ?, ?, ?)",
            [tuple(row) for row in products],
        )
        conn.executemany(
            "INSERT INTO sales "
            "(sku_id, order_id, sales, orderdate_utc, insert_timestamp_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            [tuple(row) for row in sales],
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


@pytest.fixture
def make_db(tmp_path) -> Callable[..., Path]:
    """Factory fixture: build a fresh temp SQLite DB seeded with given rows.

    Returns a callable ``make_db(products, sales) -> Path``. Each invocation
    creates a brand-new database file under the test's ``tmp_path``, so a single
    test (or hypothesis example) can build many independent databases without
    interference. The bundled ``fw/product_sales.db`` is never read or written.

    Example::

        def test_something(make_db):
            db = make_db(
                products=[(1, "widget", 9.99, "2025-01-01T00:00:00Z")],
                sales=[(1, "o1", 3, "2025-01-05", "2025-01-05T10:00:00Z")],
            )
            build_revenue(db_path=db)

    Args:
        products: Iterable of product rows (see ``PRODUCT_COLUMNS``).
        sales: Iterable of sales rows (see ``SALES_COLUMNS``). Defaults to empty.

    Returns:
        Path to the freshly created, seeded SQLite database file.
    """
    counter = {"n": 0}

    def _factory(products: Iterable[Sequence],
                 sales: Iterable[Sequence] = ()) -> Path:
        counter["n"] += 1
        db_path = tmp_path / f"revenue_test_{counter['n']}.db"
        return _seed_database(db_path, products, sales)

    return _factory


def read_revenue_rows(db_path: Path,
                      table: str = "revenue") -> list[tuple]:
    """Read back the revenue reporting columns as a deterministically ordered list.

    Returns the five reporting columns ``(sku_id, date_id, price, sales,
    revenue)`` for every row, ordered by ``sku_id`` then ``date_id`` so two
    builds (or the SQL vs Python solutions) can be compared directly with ``==``.
    The technical ``insert_timestamp_utc`` build column is intentionally excluded
    because it is a wall-clock timestamp that legitimately differs between runs.

    Args:
        db_path: Path to the SQLite database containing the revenue table.
        table: Table name to read (defaults to ``revenue``).

    Returns:
        List of ``(sku_id, date_id, price, sales, revenue)`` tuples.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            f"SELECT sku_id, date_id, price, sales, revenue "
            f"FROM {table} "
            f"ORDER BY sku_id, date_id"
        )
        return cursor.fetchall()
    finally:
        conn.close()


@pytest.fixture
def revenue_reader() -> Callable[..., list[tuple]]:
    """Fixture wrapper exposing :func:`read_revenue_rows` to tests.

    Provided as a fixture so tests can read back revenue rows without importing
    from the conftest module directly.
    """
    return read_revenue_rows
