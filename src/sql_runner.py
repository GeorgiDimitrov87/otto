"""SQL_Solution driver for the revenue-pipeline.

Executes the standalone ``sql/revenue.sql`` script against the source SQLite
database to build the ``revenue`` table, then reports how many rows were
written. The SQL script is idempotent (``DROP TABLE IF EXISTS`` followed by
``CREATE TABLE AS``), so re-runs simply replace the table.

Run as a module::

    python -m sql_runner
"""

import sqlite3
from pathlib import Path

from config import DB_PATH, REVENUE_TABLE, SQL_PATH, SQLITE_TIMEOUT


def run_sql_solution(db_path: Path = DB_PATH, sql_path: Path = SQL_PATH) -> int:
    """Execute ``sql/revenue.sql`` against ``db_path`` and return the row count.

    The SQL script (DROP + CREATE TABLE AS) runs inside a single transaction:
    it is committed on success and rolled back on any failure, so a partial
    build never leaves a half-written ``revenue`` table behind.

    Args:
        db_path: Path to the source SQLite database to build the table in.
        sql_path: Path to the SQL solution file to execute.

    Returns:
        The number of rows written to the ``revenue`` table.
    """
    sql_text = Path(sql_path).read_text(encoding="utf-8")

    connection = sqlite3.connect(db_path, timeout=SQLITE_TIMEOUT)
    try:
        # executescript() implicitly issues a COMMIT before running, so begin a
        # fresh transaction explicitly to keep the build atomic and rollbackable.
        connection.execute("BEGIN")
        connection.executescript(sql_text)
        connection.commit()

        cursor = connection.execute(f"SELECT COUNT(*) FROM {REVENUE_TABLE}")
        (row_count,) = cursor.fetchone()
        return row_count
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    written = run_sql_solution()
    print(written)
