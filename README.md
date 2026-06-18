# Revenue Pipeline

Builds a `revenue` table inside the existing SQLite database (`fw/product_sales.db`) that gives
marketing a complete product-by-day view of revenue for **January 2025** — every product, every
day, including days with zero sales.

## Assignment

The marketing department wants a PowerBI visualization showing the revenue of every product for
every day of January 2025, including days on which a product had no sales. To support it, a new
`revenue` table is generated inside `fw/product_sales.db` from the existing `product` and `sales`
tables.

The task is solved twice — once in **SQL** and once in **Python** — and the two outputs are
verified to be identical on the reporting columns.

## Solution approach

The source data has three characteristics that drive the design:

- **Duplication.** `sales` contains repeated ingestions of the same logical sale. The natural key
  `(sku_id, order_id, orderdate_utc)` can appear many times, differing only by
  `insert_timestamp_utc`. We deduplicate with `ROW_NUMBER() OVER (PARTITION BY natural key ORDER BY
  insert_timestamp_utc DESC)` and keep the latest ingestion per key. This collapses ~91,132
  physical rows down to ~7,590 logical sales; skipping it would overstate revenue many times over.
- **Out-of-period noise.** `sales` spans late December 2024 through early February 2025. The
  pipeline restricts to the reporting period **2025-01-01 through 2025-01-31 inclusive**.
- **Sparsity.** `sales` only holds products that sold. To produce a dense grid, the pipeline
  `CROSS JOIN`s `product` against a 31-day January calendar (1000 SKUs × 31 days = 31,000 rows),
  `LEFT JOIN`s the deduplicated, in-period, per-day sales totals, and uses `COALESCE` to zero-fill
  days with no sales (`sales = 0`, `revenue = 0`).

Both solutions apply the identical logical pipeline — dedup → filter → aggregate → cross join →
zero-fill → compute revenue:

- **SQL solution** (`src/revenue_pipeline/sql/revenue.sql`), executed by `sql_runner.py`.
- **Python solution** (`src/revenue_pipeline/build_revenue.py`), using only the standard library
  (`sqlite3` + `datetime`) — no third-party runtime dependencies. The Python solution drives the
  same set-based SQL with the calendar generated in Python.

The two are verified equivalent on the reporting columns `sku_id`, `date_id`, `price`, `sales`,
and `revenue`.

**Idempotency.** Each solution wraps `DROP TABLE IF EXISTS revenue` followed by table creation in
a single transaction, so re-running produces an identical table and never leaves a half-written
result.

## Output schema

The `revenue` table exposes the agreed five-column data model, plus one separate technical column:

| Column                 | Type | Description                                              |
|------------------------|------|----------------------------------------------------------|
| `sku_id`               | TEXT | Product SKU (cast to TEXT per the agreed data model)     |
| `date_id`              | DATE | Calendar day, ISO `YYYY-MM-DD`                           |
| `price`                | REAL | Unit price from `product`                                |
| `sales`                | INT  | Sum of deduplicated, in-period sales for that SKU+day    |
| `revenue`              | REAL | `price * sales`                                          |
| `insert_timestamp_utc` | TEXT | Technical build column, kept separate from the five above |

## Setup & run

The Makefile drives setup and execution:

```bash
make env          # create .venv and install dependencies
make run          # run both solutions (SQL then Python), building the revenue table
make run-sql      # run only the SQL solution
make run-python   # run only the Python solution
make test         # run the test suite
```

`make env` creates a `.venv` and installs the declared dependencies. `make run` executes both
solutions sequentially against `fw/product_sales.db`; the final `revenue` table is the Python
output, and the equivalence test asserts the two solutions agree.

## Project structure

```
.
├── README.md                  # This file
├── Makefile                   # env, run, run-sql, run-python, test targets
├── requirements.txt           # Test/dev dependencies (pytest, hypothesis)
├── fw/                        # Source assets
│   ├── product_sales.db       # SQLite database (product, sales -> revenue)
│   ├── product.csv
│   ├── sales.csv
│   └── README.md              # Original assignment brief
├── src/
│   └── revenue_pipeline/
│       ├── config.py          # Constants: DB path, period bounds, table name
│       ├── sql/revenue.sql    # SQL solution
│       ├── sql_runner.py      # Driver that executes revenue.sql
│       └── build_revenue.py   # Python solution
└── tests/                     # conftest.py + property tests + smoke test
```

## Testing

Tests run with `pytest` and `hypothesis`:

- **Property-based tests** cover the 8 design properties — deduplication, period filtering,
  complete product-by-day coverage and row count, aggregation/zero-fill, the revenue formula,
  SQL/Python equivalence, idempotency, and output-schema conformance. Each generates random
  `product`/`sales` datasets into a temporary database, so tests never touch the bundled
  `fw/product_sales.db`.
- **Real-data smoke test** runs both solutions against a copy of `fw/product_sales.db` and asserts
  exactly **31,000 rows** and that the SQL and Python outputs match — the headline acceptance check
  on the actual assignment data.

Run them with:

```bash
make test
```
