-- revenue.sql — SQL_Solution for the revenue-pipeline assignment.
--
-- Builds the `revenue` table inside the source SQLite database, giving marketing a
-- complete product-by-day view of January 2025: every SKU in `product` is represented
-- for every one of the 31 days, including days with no sales (sales = 0, revenue = 0).
--
-- One logical pipeline:
--   1. Deduplicate `sales` on the natural key (sku_id, order_id, orderdate_utc),
--      keeping the row with the latest insert_timestamp_utc.
--   2. Filter the deduped sales to January 2025 (inclusive bounds).
--   3. Aggregate SUM(sales) per SKU per day.
--   4. Build a 31-day January-2025 calendar via a recursive CTE.
--   5. CROSS JOIN product x calendar (1000 x 31 = 31,000), LEFT JOIN aggregated
--      sales, and COALESCE missing sales to 0.
--   6. Compute revenue = price * sales; cast sku_id to TEXT.
--
-- Idempotent: DROP TABLE IF EXISTS + CREATE TABLE AS, so re-runs replace the table.
-- Portable/standard constructs (window functions, CTEs, CROSS JOIN, LEFT JOIN,
-- COALESCE) so the logic maps directly to BigQuery.

DROP TABLE IF EXISTS revenue;

CREATE TABLE revenue AS
WITH
-- 1. Deduplicate sales: rank ingestions of the same natural key by recency.
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
-- 2 + 3. Filter to January 2025 and aggregate quantity per SKU per day.
daily_sales AS (
    SELECT
        sku_id,
        orderdate_utc AS date_id,
        SUM(sales) AS sales
    FROM deduped_sales
    WHERE orderdate_utc BETWEEN '2025-01-01' AND '2025-01-31'
    GROUP BY sku_id, orderdate_utc
),
-- 4. Build the 31-day January 2025 calendar.
calendar(date_id) AS (
    SELECT '2025-01-01'
    UNION ALL
    SELECT date(date_id, '+1 day')
    FROM calendar
    WHERE date_id < '2025-01-31'
)
-- 5 + 6. Dense product x day grid, zero-filled, with revenue = price * sales.
SELECT
    CAST(p.sku_id AS TEXT) AS sku_id,
    c.date_id              AS date_id,
    p.price                AS price,
    COALESCE(d.sales, 0)   AS sales,
    p.price * COALESCE(d.sales, 0) AS revenue,
    datetime('now')        AS insert_timestamp_utc
FROM product p
CROSS JOIN calendar c
LEFT JOIN daily_sales d
    ON d.sku_id = p.sku_id
   AND d.date_id = c.date_id;
