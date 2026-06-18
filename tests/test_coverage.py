"""Property-based tests for the revenue-pipeline coverage, zero-fill, and schema.

Covers three design correctness properties against the Python_Solution
(``revenue_pipeline.build_revenue.build_revenue``):

  * Property 3 — Complete product-by-day coverage with correct row count.
  * Property 4 — Aggregation and zero-fill of the sales value.
  * Property 8 — Output schema conformance.

Every test builds a fresh, hermetic temporary SQLite database (via the
``make_db`` fixture in ``conftest.py``) seeded with hypothesis-generated
``product``/``sales`` rows, runs ``build_revenue`` against it, and asserts the
property. The bundled ``fw/product_sales.db`` is never touched.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from revenue_pipeline.build_revenue import build_revenue
from revenue_pipeline.config import PERIOD_END, PERIOD_START

# --------------------------------------------------------------------------- #
# Shared constants / helpers
# --------------------------------------------------------------------------- #

# The 31 ISO date strings of the reporting period (January 2025).
_START = date.fromisoformat(PERIOD_START)
_END = date.fromisoformat(PERIOD_END)
_N_DAYS = (_END - _START).days + 1  # 31
JANUARY_DAYS = [(_START + timedelta(days=i)).isoformat() for i in range(_N_DAYS)]

# A pool of dates that includes in-period days plus just-outside boundary days,
# so generated sales exercise both the period filter and zero-fill.
OUT_OF_PERIOD_DAYS = ["2024-12-31", "2025-02-01", "2024-12-25", "2025-02-05"]
ALL_CANDIDATE_DAYS = JANUARY_DAYS + OUT_OF_PERIOD_DAYS


def _is_in_period(date_id: str) -> bool:
    return PERIOD_START <= date_id <= PERIOD_END


# --------------------------------------------------------------------------- #
# Generators
# --------------------------------------------------------------------------- #

# Small SKU sets (1–5) keep the dense 31x grid cheap while still exercising the
# cartesian product across multiple SKUs.
sku_ids = st.lists(
    st.integers(min_value=1, max_value=50),
    min_size=1,
    max_size=5,
    unique=True,
)

prices = st.floats(
    min_value=0.0,
    max_value=10_000.0,
    allow_nan=False,
    allow_infinity=False,
)

sales_quantities = st.integers(min_value=1, max_value=1000)


@st.composite
def products_and_sales(draw):
    """Generate a (products, sales, price_by_sku) bundle with UNIQUE natural keys.

    Natural keys ``(sku_id, order_id, orderdate_utc)`` are made unique so that
    deduplication is a no-op — this isolates Properties 3/4/8 from dedup logic.
    Multiple distinct orders may still land on the same (SKU, day), exercising
    SUM aggregation; some (SKU, day) combinations are deliberately left without
    any sales to exercise zero-fill.
    """
    skus = draw(sku_ids)

    price_by_sku = {sku: draw(prices) for sku in skus}
    products = [
        (sku, f"sku-{sku}", price_by_sku[sku], "2025-01-01T00:00:00Z")
        for sku in skus
    ]

    # Generate sales rows. Each row gets a globally-unique order_id, guaranteeing
    # unique natural keys regardless of (sku, day) collisions.
    sale_specs = draw(
        st.lists(
            st.tuples(
                st.sampled_from(skus),
                st.sampled_from(ALL_CANDIDATE_DAYS),
                sales_quantities,
            ),
            min_size=0,
            max_size=20,
        )
    )

    sales = []
    for idx, (sku, day, qty) in enumerate(sale_specs):
        order_id = f"order-{idx}"  # unique per row -> unique natural key
        sales.append((sku, order_id, qty, day, "2025-01-10T00:00:00Z"))

    return products, sales, price_by_sku


# --------------------------------------------------------------------------- #
# Property 3: Complete product-by-day coverage with correct row count
# --------------------------------------------------------------------------- #
# Feature: revenue-pipeline, Property 3: Complete product-by-day coverage with correct row count
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=products_and_sales())
def test_property_3_complete_coverage(make_db, revenue_reader, data):
    """The revenue table has exactly n_skus * 31 rows: the full SKU x day grid.

    Validates: Requirements 5.1, 5.4
    """
    products, sales, _ = data
    db = make_db(products=products, sales=sales)

    written = build_revenue(db_path=db)

    distinct_skus = {p[0] for p in products}
    expected_count = len(distinct_skus) * _N_DAYS

    # build_revenue returns the written row count.
    assert written == expected_count

    rows = revenue_reader(db)
    assert len(rows) == expected_count

    # Exactly one row per (sku_id, date_id) — no duplicates, no missing combos.
    pairs = [(r[0], r[1]) for r in rows]
    assert len(pairs) == len(set(pairs)), "duplicate (sku_id, date_id) rows found"

    expected_pairs = {
        (str(sku), day) for sku in distinct_skus for day in JANUARY_DAYS
    }
    assert set(pairs) == expected_pairs


# --------------------------------------------------------------------------- #
# Property 4: Aggregation and zero-fill of the sales value
# --------------------------------------------------------------------------- #
# Feature: revenue-pipeline, Property 4: Aggregation and zero-fill of the sales value
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=products_and_sales())
def test_property_4_aggregation_and_zero_fill(make_db, revenue_reader, data):
    """Each cell's sales == sum of retained in-period sales for that SKU/day, else 0.

    Validates: Requirements 5.2, 5.3
    """
    products, sales, _ = data
    db = make_db(products=products, sales=sales)

    build_revenue(db_path=db)

    # Compute the expected per-(sku, day) sum in Python. Natural keys are unique,
    # so dedup is a no-op; only in-period sales contribute.
    expected = {}
    for sku_id, _order_id, qty, day, _ts in sales:
        if not _is_in_period(day):
            continue
        expected[(str(sku_id), day)] = expected.get((str(sku_id), day), 0) + qty

    rows = revenue_reader(db)
    for sku_id, date_id, _price, sales_val, _revenue in rows:
        expected_sales = expected.get((sku_id, date_id), 0)
        assert sales_val == expected_sales, (
            f"sku={sku_id} day={date_id}: got {sales_val}, expected {expected_sales}"
        )

    # Sanity: cells with no in-period sales must be exactly 0 (zero-fill).
    cells_with_sales = set(expected)
    zero_cells = [
        (r[0], r[1], r[3]) for r in rows if (r[0], r[1]) not in cells_with_sales
    ]
    assert all(sv == 0 for _s, _d, sv in zero_cells)


# --------------------------------------------------------------------------- #
# Property 8: Output schema conformance
# --------------------------------------------------------------------------- #
EXPECTED_REPORTING_COLUMNS = ["sku_id", "date_id", "price", "sales", "revenue"]
TECHNICAL_COLUMN = "insert_timestamp_utc"


# Feature: revenue-pipeline, Property 8: Output schema conformance
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=products_and_sales())
def test_property_8_schema_conformance(make_db, data):
    """The revenue table exposes the five reporting columns (named/ordered exactly),
    with the technical insert_timestamp_utc column appended separately after them,
    and the runtime value types match the agreed data model.

    Validates: Requirements 6.1, 6.4
    """
    products, sales, _ = data
    db = make_db(products=products, sales=sales)

    build_revenue(db_path=db)

    conn = sqlite3.connect(str(db))
    try:
        # --- Column names / order via PRAGMA table_info -------------------- #
        info = conn.execute("PRAGMA table_info(revenue)").fetchall()
        col_names = [row[1] for row in info]  # (cid, name, type, ...)

        # First five reporting columns present, named and ordered exactly.
        assert col_names[:5] == EXPECTED_REPORTING_COLUMNS

        # Technical column is SEPARATE: present, AFTER the five, not one of them.
        assert TECHNICAL_COLUMN in col_names
        assert TECHNICAL_COLUMN not in EXPECTED_REPORTING_COLUMNS
        assert col_names.index(TECHNICAL_COLUMN) >= 5

        # --- Runtime value types via typeof() ------------------------------ #
        # CREATE TABLE AS may not record declared affinities, so assert on the
        # actual stored value types (robust to SQLite dynamic typing).
        row = conn.execute(
            "SELECT sku_id, date_id, price, sales, revenue, "
            "typeof(sku_id), typeof(date_id), typeof(price), "
            "typeof(sales), typeof(revenue) "
            "FROM revenue LIMIT 1"
        ).fetchone()

        if row is not None:
            sku_id, date_id, _price, _sv, _rev = row[:5]
            t_sku, t_date, t_price, t_sales, t_rev = row[5:]

            # sku_id renders as TEXT and is not a float-formatted string.
            assert t_sku == "text"
            assert isinstance(sku_id, str)
            assert not sku_id.endswith(".0")

            # date_id is ISO text (SQLite has no dedicated DATE type).
            assert t_date == "text"
            assert isinstance(date_id, str)
            assert date_id in JANUARY_DAYS

            # sales is an integer count.
            assert t_sales == "integer"

            # price and revenue are numeric (real, or integer for whole numbers).
            assert t_price in ("real", "integer")
            assert t_rev in ("real", "integer")
    finally:
        conn.close()
