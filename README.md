# Revenue Pipeline

Builds a `revenue` table inside the existing SQLite database (`fw/product_sales.db`) that gives
marketing a complete product-by-day view of revenue for **January 2025** — every product, every
day, including days with zero sales.

## Assignment

The marketing department wants a PowerBI visualization showing the revenue of every product for
every day of January 2025, including days on which a product had no sales. To support it, a new
`revenue` table is generated inside `fw/product_sales.db`.

The task is solved twice — once in **SQL** and once in **Python** — and the two outputs are
verified to be identical on the reporting columns.

## Solution approach

The source data has three characteristics that drive the design:

- **Duplication.** The sales data contains repeated ingestions of the same logical sale. The
  natural key `(sku_id, order_id, orderdate_utc)` can appear many times, differing only by
  `insert_timestamp_utc`. Both solutions deduplicate by keeping the latest ingestion per natural
  key (the row with the greatest `insert_timestamp_utc`). Skipping this would overstate revenue
  many times over.

- **Out-of-period noise.** The sales data spans late December 2024 through early February 2025.
  The pipeline restricts to the reporting period **2025-01-01 through 2025-01-31 inclusive**.

- **Sparsity.** The sales data only holds products that sold. To produce a dense grid, the
  pipeline pairs every product with every January day (1000 SKUs × 31 days = 31,000 rows), joins
  the deduplicated, in-period, per-day sales totals, and zero-fills days with no sales
  (`sales = 0`, `revenue = 0`).

Both solutions apply the identical logical pipeline — dedup → period filter → aggregate → dense
product-by-day grid → zero-fill → compute `revenue = price * sales` — and are implemented
independently:

### SQL solution

`src/sql/revenue.sql`, executed by `src/sql_runner.py`. This is the set-based solution: it reads
the `product` and `sales` tables directly from `fw/product_sales.db`, deduplicates with
`ROW_NUMBER() OVER (PARTITION BY natural key ORDER BY insert_timestamp_utc DESC)`, `CROSS JOIN`s
`product` against a 31-day January calendar, `LEFT JOIN`s the per-day sales totals, and uses
`COALESCE` to zero-fill. Run it on its own with `make run-sql`.

### Python solution

A CSV-sourced ETL that uses **only the Python standard library** (`csv`, `collections`,
`datetime`, `itertools`, `sqlite3`) — **no pandas and no third-party runtime dependencies**. It
reads the source CSV files (`fw/product.csv`, `fw/sales.csv`), **not** the database tables, and is
split into three reusable modules plus a thin runner:

- **`src/extract.py`** — reads `fw/product.csv` and `fw/sales.csv` into `list[dict]` rows.
- **`src/transform.py`** — pure standard-library transformation: deduplicate to the latest
  ingestion per natural key → filter to the January 2025 period → aggregate per SKU and day →
  build the dense product-by-day grid → zero-fill missing days → compute `revenue = price * sales`.
- **`src/load.py`** — writes the resulting rows into the `revenue` table in `fw/product_sales.db`
  inside a single atomic transaction (so a failure never leaves a half-written table).
- **`src/run_python.py`** — the standalone runner and entry point for `make run-python`. It calls
  `extract → transform → load` in order, contains no business logic, and imports no third-party
  packages.

Run the Python solution on its own with `make run-python`.

The two solutions are verified equivalent on the reporting columns `sku_id`, `date_id`, `price`,
`sales`, and `revenue`. Each is idempotent: re-running drops and rebuilds the `revenue` table so a
second run produces an identical table and never leaves a partial result.

## Dependencies

The Python solution needs **no third-party runtime dependency** — `make run-python` and the test
suite run on the standard library alone (no pandas).

- **`requirements.txt`** — test/dev tooling only: `pytest` and `hypothesis`. Installed by
  `make env`.

## Output schema

The `revenue` table exposes the agreed five reporting columns, plus one separate technical column:

| Column                 | Type | Description                                              |
|------------------------|------|----------------------------------------------------------|
| `sku_id`               | TEXT | Product SKU, rendered as TEXT per the agreed data model  |
| `date_id`              | DATE | Calendar day, ISO `YYYY-MM-DD`                           |
| `price`                | REAL | Unit price from `product`                                |
| `sales`                | INT  | Sum of deduplicated, in-period sales for that SKU+day    |
| `revenue`              | REAL | `price * sales`                                          |
| `insert_timestamp_utc` | TEXT | Technical build column, kept separate from the five above |

## Setup & run

The Makefile drives setup and execution. Every target runs with `PYTHONPATH=src`:

```bash
make env          # create .venv and install requirements.txt (pytest, hypothesis)
make run          # run-sql then run-python, in that order (fail-fast)
make run-sql      # run only the SQL solution  (python -m sql_runner)
make run-python   # run only the Python solution (python -m run_python)
make test         # run the test suite (python -m pytest)
```

- **`env`** creates a `.venv` and installs `requirements.txt` into it.
- **`run`** runs `run-sql` then `run-python` sequentially; if the SQL solution fails, the Python
  solution does not run.
- **`run-sql`** executes `python -m sql_runner`, applying `src/sql/revenue.sql` to
  `fw/product_sales.db`.
- **`run-python`** executes `python -m run_python`, running the CSV-sourced ETL.
- **`test`** executes `python -m pytest`.

The final `revenue` table after `make run` is the Python output; the equivalence test asserts the
two solutions agree.

## Project structure

```
.
├── README.md                  # This file
├── PROJECT_DECISIONS.md       # Committed decision record for reviewers
├── Makefile                   # env, run, run-sql, run-python, test targets
├── requirements.txt           # Test/dev tooling only (pytest, hypothesis)
├── fw/                        # Source assets
│   ├── product_sales.db       # SQLite database (product, sales -> revenue)
│   ├── product.csv            # Source CSV read by the Python solution
│   ├── sales.csv              # Source CSV read by the Python solution
│   └── README.md              # Original assignment brief
├── src/
│   ├── config.py              # Constants: DB/CSV paths, period bounds, table name
│   ├── extract.py             # Python solution: read CSVs -> list[dict]
│   ├── transform.py           # Python solution: stdlib dedup/filter/aggregate/zero-fill
│   ├── load.py                # Python solution: atomic write of revenue table
│   ├── run_python.py          # Standalone runner for `make run-python`
│   ├── sql_runner.py          # Driver that executes revenue.sql
│   └── sql/revenue.sql        # SQL solution
└── tests/                     # conftest.py + property tests + smoke test
```

## Testing

Tests run with `pytest` and `hypothesis`. Property-based tests generate random `product`/`sales`
datasets into a temporary database, so they never touch the bundled `fw/product_sales.db`.

- **`tests/test_dedup.py`** — Property 1: deduplication keeps the latest ingestion per natural key.
- **`tests/test_period_filter.py`** — Property 2: period filter keeps exactly January 2025,
  including the boundary days.
- **`tests/test_coverage_prop3.py`** — Property 3: complete product-by-day coverage and the dynamic
  row count (products × days).
- **`tests/test_coverage_prop4.py`** — Property 4: aggregation and zero-fill of days with no sales.
- **`tests/test_revenue_formula.py`** — Property 5: `revenue = price × sales`.
- **`tests/test_equivalence.py`** — Property 6: the SQL and Python solutions produce identical
  reporting columns.
- **`tests/test_idempotency.py`** — Property 7: idempotent execution, parametrised over both the
  SQL and Python solutions.
- **`tests/test_schema.py`** — Property 8: output-schema conformance and `sku_id` rendered as TEXT.
- **`tests/test_smoke.py`** — real-data smoke test: runs both solutions against a copy of
  `fw/product_sales.db` and asserts exactly **31,000 rows** and SQL/Python agreement.
- **`tests/test_config_validation.py`** — asserts the config matches the bundled data specs
  (1000 products × 31 days = 31,000 rows).
- **`tests/test_extract_missing.py`** — CSV-missing edge case: a descriptive error with no partial
  write.
- **`tests/test_load_atomic.py`** — atomic-load rollback: a load failure leaves no partial write.
- **`tests/test_no_airflow_imports.py`** — the ETL modules import and run without `apache-airflow`
  installed.

Run them with:

```bash
make test
```
