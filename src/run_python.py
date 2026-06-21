"""Standalone_Runner: the no-Airflow entry point for ``make run-python``.

This thin orchestrator runs the CSV-sourced, standard-library Python_Solution as
``extract -> transform -> load`` by calling the reusable ETL_Modules directly.
It **replaces** the old ``build_revenue.py`` (which drove the same set-based SQL
from Python and therefore did not differentiate the two solutions).

It contains **no business logic** and has **no Apache Airflow import and no
pandas** — all the real logic lives in :mod:`extract`, :mod:`transform`, and
:mod:`load`, so the runner needs nothing beyond CPython's standard library.

Run as a module::

    PYTHONPATH=src python -m run_python
"""

from __future__ import annotations

from config import DB_PATH, PERIOD_END, PERIOD_START, PRODUCT_CSV, SALES_CSV
from extract import extract
from load import write_revenue
from transform import transform


def main(product_csv=PRODUCT_CSV,
         sales_csv=SALES_CSV,
         db_path=DB_PATH,
         period_start=PERIOD_START,
         period_end=PERIOD_END) -> int:
    """Run the Python_Solution end-to-end and return the row count written.

    Calls the ETL_Modules in order: :func:`extract.extract` reads the
    Source_CSV files, :func:`transform.transform` builds the dense ``revenue``
    rows, and :func:`load.write_revenue` writes them into the Source_DB inside a
    single atomic transaction. A missing/unreadable CSV raises a descriptive
    error during extract, before any database write, so a bad input never
    produces a partial Revenue_Table.

    Args:
        product_csv: Path to the product CSV. Defaults to :data:`config.PRODUCT_CSV`.
        sales_csv: Path to the sales CSV. Defaults to :data:`config.SALES_CSV`.
        db_path: Path to the source SQLite database. Defaults to :data:`config.DB_PATH`.
        period_start: Inclusive Reporting_Period start (ISO date string).
        period_end: Inclusive Reporting_Period end (ISO date string).

    Returns:
        The number of rows written to the ``revenue`` table.
    """
    products, sales = extract(product_csv, sales_csv)
    revenue = transform(products, sales, period_start, period_end)
    return write_revenue(revenue, db_path)


if __name__ == "__main__":
    print(main())
