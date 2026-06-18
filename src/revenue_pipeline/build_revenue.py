"""build_revenue.py — Python_Solution for the revenue-pipeline assignment.

Builds the ``revenue`` table inside the source SQLite database, giving marketing a
complete product-by-day view of January 2025: every SKU in ``product`` is represented
for every one of the 31 days, including days with no sales (sales = 0, revenue = 0).

This is the same logical pipeline as ``sql/revenue.sql``, driven from Python with the
standard library only (``sqlite3`` + ``datetime`` — no pandas, no third-party deps):

  1. Deduplicate ``sales`` on the natural key (sku_id, order_id, orderdate_utc),
     keeping the row with the latest insert_timestamp_utc.
  2. Filter the deduped sales to the reporting period (inclusive bounds).
  3. Aggregate SUM(sales) per SKU per day.
  4. Build the calendar in Python from the period bounds with ``datetime`` (not a
     hard-coded count, not a recursive CTE) and inject it as a temporary table.
  5. CROSS JOIN product x calendar, LEFT JOIN aggregated sales, COALESCE missing
     sales to 0.
  6. Compute revenue = price * sales; CAST(sku_id AS TEXT).

Identical casts and arithmetic order to the SQL solution so the two outputs match
exactly on the reporting columns. Idempotent: DROP TABLE IF EXISTS + CREATE inside a
single transaction (commit on success, rollback on failure).
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

from revenue_pipeline.config import DB_PATH, PERIOD_END, PERIOD_START, REVENUE_TABLE


def _build_calendar(period_start: str, period_end: str) -> list[str]:
    """Generate the list of ISO date strings in [period_start, period_end] inclusive.

    The count is derived from the period bounds (not hard-coded): for January 2025
    this yields the 31 dates 2025-01-01 .. 2025-01-31.
    """
    start = date.fromisoformat(period_start)
    end = date.fromisoformat(period_end)
    n_days = (end - start).days + 1
    return [(start + timedelta(days=i)).isoformat() for i in range(n_days)]


def build_revenue(
    db_path: Path = DB_PATH,
    period_start: str = PERIOD_START,
    period_end: str = PERIOD_END,
) -> int:
    """Build the ``revenue`` table in ``db_path``. Returns the row count written.

    Mirrors ``sql/revenue.sql`` exactly on the reporting columns (sku_id, date_id,
    price, sales, revenue), with a separate technical ``insert_timestamp_utc`` build
    column appended after them.
    """
    calendar = _build_calendar(period_start, period_end)

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        # Single transaction for idempotent replacement: if anything fails midway the
        # previous revenue table is left intact.
        cur.execute("BEGIN")

        # 4. Inject the Python-built calendar as a temporary table.
        cur.execute("DROP TABLE IF EXISTS _calendar")
        cur.execute("CREATE TEMP TABLE _calendar (date_id TEXT)")
        cur.executemany(
            "INSERT INTO _calendar (date_id) VALUES (?)",
            [(d,) for d in calendar],
        )

        cur.execute(f"DROP TABLE IF EXISTS {REVENUE_TABLE}")

        # 1-3 + 5-6: same logical pipeline as the SQL solution. The period bounds are
        # passed as bound parameters; the calendar comes from the injected temp table
        # instead of the SQL recursive CTE.
        cur.execute(
            f"""
            CREATE TABLE {REVENUE_TABLE} AS
            WITH
            ranked_sales AS (
                SELECT
                    sku_id,
                    order_id,
                    orderdate_utc,
                    sales,
                    ROW_NUMBER() OVER (
                        PARTITION BY sku_id, order_id, orderdate_utc
                        ORDER BY insert_timestamp_utc DESC
                    ) AS rn
                FROM sales
            ),
            deduped_sales AS (
                SELECT sku_id, order_id, orderdate_utc, sales
                FROM ranked_sales
                WHERE rn = 1
            ),
            daily_sales AS (
                SELECT
                    sku_id,
                    orderdate_utc AS date_id,
                    SUM(sales) AS sales
                FROM deduped_sales
                WHERE orderdate_utc BETWEEN ? AND ?
                GROUP BY sku_id, orderdate_utc
            )
            SELECT
                CAST(p.sku_id AS TEXT) AS sku_id,
                c.date_id              AS date_id,
                p.price                AS price,
                COALESCE(d.sales, 0)   AS sales,
                p.price * COALESCE(d.sales, 0) AS revenue,
                datetime('now')        AS insert_timestamp_utc
            FROM product p
            CROSS JOIN _calendar c
            LEFT JOIN daily_sales d
                ON d.sku_id = p.sku_id
               AND d.date_id = c.date_id
            """,
            (period_start, period_end),
        )

        cur.execute("DROP TABLE IF EXISTS _calendar")

        row_count = cur.execute(
            f"SELECT COUNT(*) FROM {REVENUE_TABLE}"
        ).fetchone()[0]

        conn.commit()
        return row_count
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    written = build_revenue()
    print(written)
