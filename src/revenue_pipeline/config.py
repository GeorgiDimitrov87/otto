"""Shared configuration constants for the revenue pipeline.

Defines the source database location, the output table name, the fixed
January 2025 reporting period bounds, and the path to the SQL solution file.
"""

from pathlib import Path

# Source SQLite database. config.py lives at src/revenue_pipeline/config.py, so
# parents[0] = revenue_pipeline, parents[1] = src, parents[2] = repository root.
DB_PATH = Path(__file__).resolve().parents[2] / "fw" / "product_sales.db"

# Output table written into the source database.
REVENUE_TABLE = "revenue"

# Reporting period: January 2025, both bounds inclusive.
PERIOD_START = "2025-01-01"  # inclusive
PERIOD_END = "2025-01-31"  # inclusive

# SQL solution file, kept alongside this package in the sql/ directory.
SQL_PATH = Path(__file__).resolve().parent / "sql" / "revenue.sql"
