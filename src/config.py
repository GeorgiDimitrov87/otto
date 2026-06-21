"""Shared configuration constants for the revenue pipeline.

Defines the source database location, the Source_CSV file locations, the output
table name, the fixed January 2025 reporting period bounds, the path to the SQL
solution file, and the SQLite connection timeout used as a lock hang-guard.
"""

from pathlib import Path

# Source SQLite database. config.py lives at src/config.py, so parents[0] = src
# and parents[1] = repository root.
DB_PATH = Path(__file__).resolve().parents[1] / "fw" / "product_sales.db"

# Source CSV inputs read by the Python_Solution (Extract_Module).
PRODUCT_CSV = Path(__file__).resolve().parents[1] / "fw" / "product.csv"
SALES_CSV = Path(__file__).resolve().parents[1] / "fw" / "sales.csv"

# Output table written into the source database.
REVENUE_TABLE = "revenue"

# Reporting period: January 2025, both bounds inclusive.
PERIOD_START = "2025-01-01"  # inclusive
PERIOD_END = "2025-01-31"  # inclusive

# SQL solution file, kept alongside this module in the sql/ directory.
SQL_PATH = Path(__file__).resolve().parent / "sql" / "revenue.sql"

# Positive SQLite connection timeout (seconds): brief lock contention is retried
# rather than failing immediately, and a blocked connection cannot wait forever.
SQLITE_TIMEOUT = 5
