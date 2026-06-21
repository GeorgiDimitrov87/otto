"""Property-based test for the revenue-pipeline output schema conformance.

# Feature: revenue-pipeline, Property 8: Output schema conformance and sku_id TEXT rendering

For any generated ``products`` / ``sales`` bundle, every row returned by
:func:`transform.transform` exposes exactly the five reporting fields in the
canonical order ``[sku_id, date_id, price, sales, revenue]`` with the agreed
runtime value types:

  * ``sku_id``  — a ``str`` rendered from the integer SKU, never ending in
    ``".0"`` (canonical digits-only decimal text, matching the SQL
    ``CAST(p.sku_id AS TEXT)``);
  * ``date_id`` — ISO date text within the January 2025 reporting period;
  * ``price``   — ``float``;
  * ``sales``   — ``int``;
  * ``revenue`` — ``float``.

Note on the technical column: :func:`transform.transform` returns plain dicts
holding only the FIVE reporting fields. The technical ``insert_timestamp_utc``
column is NOT produced by ``transform`` — it is appended separately, *after* the
five reporting columns, by the load step (``load.py``, task 4.1). This test
therefore asserts that the transform output contains exactly the five reporting
fields and never carries ``insert_timestamp_utc`` itself.

Validates: Requirements 5.1, 5.4, 5.6
"""

from __future__ import annotations

from datetime import date, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from config import PERIOD_END, PERIOD_START
from transform import transform

# --------------------------------------------------------------------------- #
# Shared constants
# --------------------------------------------------------------------------- #

# The five reporting fields in their canonical order. The technical
# insert_timestamp_utc column is appended later by the load step, not here.
EXPECTED_REPORTING_KEYS = ["sku_id", "date_id", "price", "sales", "revenue"]
TECHNICAL_COLUMN = "insert_timestamp_utc"

# The ISO date strings of the inclusive reporting period (January 2025).
_START = date.fromisoformat(PERIOD_START)
_END = date.fromisoformat(PERIOD_END)
_N_DAYS = (_END - _START).days + 1  # 31
JANUARY_DAYS = {(_START + timedelta(days=i)).isoformat() for i in range(_N_DAYS)}

# Out-of-period days so generated sales also exercise the period filter; they
# must never alter the schema of any emitted row.
OUT_OF_PERIOD_DAYS = ["2024-12-31", "2025-02-01", "2024-12-25", "2025-02-05"]
ALL_CANDIDATE_DAYS = sorted(JANUARY_DAYS) + OUT_OF_PERIOD_DAYS


# --------------------------------------------------------------------------- #
# Generators
# --------------------------------------------------------------------------- #

# Small SKU sets keep the dense 31-day grid cheap while still covering multiple
# SKUs (so sku_id rendering is exercised across distinct integer values).
sku_ids = st.lists(
    st.integers(min_value=1, max_value=10_000_000),
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
    """Generate (products, sales) dict bundles with UNIQUE natural keys.

    Each sales row gets a globally-unique ``order_id`` so deduplication is a
    no-op and the schema of the output is the only thing under test. Some
    (SKU, day) cells are left without sales to exercise zero-fill, and some
    sales fall outside the period to exercise the filter — neither must change
    the per-row schema.
    """
    skus = draw(sku_ids)

    products = [
        {
            "sku_id": sku,
            "sku_description": f"sku-{sku}",
            "price": draw(prices),
            "insert_timestamp_utc": "2025-01-01T00:00:00Z",
        }
        for sku in skus
    ]

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

    sales = [
        {
            "sku_id": sku,
            "order_id": f"order-{idx}",  # unique per row -> unique natural key
            "sales": qty,
            "orderdate_utc": day,
            "insert_timestamp_utc": "2025-01-10T00:00:00Z",
        }
        for idx, (sku, day, qty) in enumerate(sale_specs)
    ]

    return products, sales


# --------------------------------------------------------------------------- #
# Property 8: Output schema conformance and sku_id TEXT rendering
# --------------------------------------------------------------------------- #
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(data=products_and_sales())
def test_property_8_schema_conformance(data):
    """Every transform row has exactly the five reporting fields, in order, with
    the agreed value types; sku_id is TEXT and never ends in ".0".

    Validates: Requirements 5.1, 5.4, 5.6
    """
    products, sales = data

    rows = transform(products, sales)

    # The dense grid is always non-empty (>= 1 SKU x 31 days).
    assert rows, "transform unexpectedly produced no rows"
    assert len(rows) == len(products) * _N_DAYS

    for row in rows:
        # --- Five reporting fields, exact set and canonical order ---------- #
        assert list(row.keys()) == EXPECTED_REPORTING_KEYS, (
            f"unexpected keys/order: {list(row.keys())}"
        )

        # The technical column is added later by the load step, never here.
        assert TECHNICAL_COLUMN not in row
        assert TECHNICAL_COLUMN not in EXPECTED_REPORTING_KEYS

        # --- sku_id: TEXT, canonical decimal, never float-formatted -------- #
        sku_id = row["sku_id"]
        assert isinstance(sku_id, str), f"sku_id not str: {sku_id!r}"
        assert not sku_id.endswith(".0"), f"sku_id float-formatted: {sku_id!r}"
        assert sku_id.isdigit(), f"sku_id not digits-only text: {sku_id!r}"

        # --- date_id: ISO text within the reporting period ----------------- #
        date_id = row["date_id"]
        assert isinstance(date_id, str), f"date_id not str: {date_id!r}"
        # Parseable as an ISO date and falls inside January 2025.
        parsed = date.fromisoformat(date_id)
        assert _START <= parsed <= _END
        assert date_id in JANUARY_DAYS

        # --- price: float -------------------------------------------------- #
        assert isinstance(row["price"], float), f"price not float: {row['price']!r}"

        # --- sales: int (and not a bool, which is an int subclass) --------- #
        sales_val = row["sales"]
        assert isinstance(sales_val, int) and not isinstance(sales_val, bool), (
            f"sales not int: {sales_val!r}"
        )

        # --- revenue: float ------------------------------------------------ #
        assert isinstance(row["revenue"], float), (
            f"revenue not float: {row['revenue']!r}"
        )
