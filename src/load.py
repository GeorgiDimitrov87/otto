"""Load_Module: write the dense ``revenue`` rows into the Source_DB.

This is the Load step of the CSV-sourced, standard-library Python_Solution. It
takes the row dicts produced by :func:`transform.transform` and writes them into
the ``revenue`` table of the source SQLite database using **only the standard
:mod:`sqlite3` module** — there is no pandas and no Apache Airflow import.

Atomicity, idempotence, and the connection timeout
--------------------------------------------------
The whole rebuild — ``DROP TABLE IF EXISTS revenue`` + an explicit
``CREATE TABLE`` + the bulk ``executemany`` insert — runs inside **one
transaction**. It is committed only on success and rolled back on any failure,
so a reader observes either the previous ``revenue`` table or the fully rebuilt
one, never a partial write (the atomic-rebuild guarantee of criterion 4.5). The
DROP-then-CREATE shape also makes re-runs idempotent: running the loader twice
yields the same table (criterion 2.9).

Every connection is opened with ``timeout=SQLITE_TIMEOUT`` so brief lock
contention against the SQL_Solution is retried rather than failing instantly,
and a blocked write can never wait forever (the hang-guard of criterion 4.1).

Schema (matching the SQL_Solution output)
-----------------------------------------
The table is created with an **explicit** ``CREATE TABLE`` rather than
``CREATE TABLE AS`` so the column affinities are declared, not inferred. In
particular ``sku_id`` is declared ``TEXT`` (TEXT affinity, matching the SQL
``CAST(p.sku_id AS TEXT)``), alongside ``date_id TEXT``, ``price REAL``,
``sales INTEGER``, ``revenue REAL``, and the technical ``insert_timestamp_utc
TEXT`` build column appended after the five reporting columns.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH, REVENUE_TABLE, SQLITE_TIMEOUT

# Output column order: the five reporting columns followed by the technical
# build column. ``sku_id`` is declared TEXT so the column has TEXT affinity
# (matching the SQL solution's CAST(p.sku_id AS TEXT)).
_COLUMNS_DDL = (
    "sku_id TEXT",
    "date_id TEXT",
    "price REAL",
    "sales INTEGER",
    "revenue REAL",
    "insert_timestamp_utc TEXT",
)

# The reporting-column keys, in canonical order, read out of each row dict.
_REPORTING_KEYS = ("sku_id", "date_id", "price", "sales", "revenue")


def write_revenue(revenue: list[dict],
                  db_path: Path = DB_PATH,
                  table: str = REVENUE_TABLE) -> int:
    """Rebuild ``table`` from ``revenue`` rows inside one transaction.

    Opens ``sqlite3.connect(db_path, timeout=SQLITE_TIMEOUT)``, begins an
    explicit transaction, drops and recreates ``table`` via an explicit
    ``CREATE TABLE`` (declaring ``sku_id TEXT`` for TEXT affinity), and bulk
    inserts the rows with ``executemany``. A technical ``insert_timestamp_utc``
    column (a single UTC build timestamp shared by every row of this build) is
    appended after the five reporting columns. The transaction is committed on
    success and rolled back on any failure, so the rebuild is atomic — a reader
    sees either the previous table or the fully rebuilt one, never a partial
    write — and idempotent across re-runs.

    Args:
        revenue: Row dicts from :func:`transform.transform`, each with keys
            ``[sku_id (str), date_id (str), price (float), sales (int),
            revenue (float)]``.
        db_path: Path to the source SQLite database. Defaults to
            :data:`config.DB_PATH`.
        table: Name of the output table. Defaults to :data:`config.REVENUE_TABLE`.

    Returns:
        The number of rows written to ``table``.
    """
    insert_timestamp_utc = datetime.now(timezone.utc).isoformat()

    # Materialise the insert tuples in canonical column order, appending the
    # shared technical build timestamp as the final column of each row.
    insert_rows = [
        (
            row["sku_id"],
            row["date_id"],
            row["price"],
            row["sales"],
            row["revenue"],
            insert_timestamp_utc,
        )
        for row in revenue
    ]

    create_sql = f"CREATE TABLE {table} ({', '.join(_COLUMNS_DDL)})"
    insert_sql = (
        f"INSERT INTO {table} "
        f"(sku_id, date_id, price, sales, revenue, insert_timestamp_utc) "
        f"VALUES (?, ?, ?, ?, ?, ?)"
    )

    connection = sqlite3.connect(db_path, timeout=SQLITE_TIMEOUT)
    try:
        # Explicit BEGIN so the DROP + CREATE + bulk insert form one atomic,
        # rollbackable unit (commit on success, rollback on any failure).
        connection.execute("BEGIN")
        connection.execute(f"DROP TABLE IF EXISTS {table}")
        connection.execute(create_sql)
        connection.executemany(insert_sql, insert_rows)
        connection.commit()
        return len(insert_rows)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
