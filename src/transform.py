"""Transform_Module: the pure, standard-library heart of the Python_Solution.

This module takes the extracted ``products`` and ``sales`` row lists (plain
``list[dict]`` produced by :mod:`extract`) and returns the dense ``revenue``
rows — one row per ``(product, day)`` over the Reporting_Period, zero-filled for
days with no sales. It uses **only the Python standard library**
(:mod:`collections`, :mod:`datetime`, :mod:`itertools`): there is **no Apache
Airflow import, no pandas, and no database access**. That purity is what lets
the property tests call :func:`transform` directly on in-memory data.

Logical pipeline (the standard-library analogue of ``sql/revenue.sql``)::

    dedup -> period filter -> aggregate -> dense product x day grid
          -> zero-fill -> revenue = price * sales

Each step is a small, named helper so a walkthrough can point at one function
per concept:

1. :func:`deduplicate`    — one row per Natural_Key, latest ``insert_timestamp_utc`` wins.
2. :func:`filter_period`  — keep ISO ``orderdate_utc`` within the inclusive bounds.
3. :func:`aggregate_daily`— SUM ``sales`` per ``(sku_id, orderdate_utc)``.
4. :func:`build_calendar` — the inclusive day list, derived dynamically from bounds.
5. :func:`build_grid`     — ``itertools.product(products, calendar)`` with zero-fill.
6. :func:`compute_revenue`— ``revenue = price * sales``; render ``sku_id`` as ``str``.

Ordering & equivalence note
---------------------------
The output is ordered by ``(sku_id, date_id)``. ``sku_id`` is rendered to its
canonical decimal string and the sort uses that **string** value, matching how
the SQL_Solution stores ``sku_id`` as TEXT and how SQLite's default (BINARY)
collation orders it on read-back. Sorting on the rendered string therefore keeps
the Python row order consistent with the SQL row order (digits-only strings of
equal length sort identically whether compared as text or as integers; the
shared string sort is the safe, exactly-matching choice).
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from datetime import date, timedelta

from config import PERIOD_END, PERIOD_START

# Natural_Key fields identifying one logical sale.
_NATURAL_KEY = ("sku_id", "order_id", "orderdate_utc")


def deduplicate(sales: list[dict]) -> list[dict]:
    """Collapse repeated ingestions of a Natural_Key to a single latest row.

    Retains exactly one row per Natural_Key ``(sku_id, order_id, orderdate_utc)``
    — the one with the maximum ``insert_timestamp_utc`` — by folding the rows
    into a dict keyed by the natural key and replacing the stored row whenever a
    strictly later ``insert_timestamp_utc`` is seen. Duplicates collapse to one
    logical sale (they are never summed), so each Natural_Key contributes its
    quantity to revenue at most once.

    Tie behaviour: if two ingestions of the same key share an identical
    ``insert_timestamp_utc``, the retained row is whichever appears first in
    ``sales`` (the strict ``>`` comparison keeps the earlier-seen row). This
    matches the documented "no secondary tiebreaker / non-deterministic among
    ties" position.

    Args:
        sales: Sales row dicts with at least the natural-key fields and
            ``insert_timestamp_utc``.

    Returns:
        A list of deduplicated sales row dicts (one per natural key).
    """
    latest: dict[tuple, dict] = {}
    for row in sales:
        key = (row["sku_id"], row["order_id"], row["orderdate_utc"])
        current = latest.get(key)
        if current is None or row["insert_timestamp_utc"] > current["insert_timestamp_utc"]:
            latest[key] = row
    return list(latest.values())


def filter_period(sales: list[dict], start: str, end: str) -> list[dict]:
    """Keep only sales whose ``orderdate_utc`` falls within the inclusive bounds.

    ISO date strings (``YYYY-MM-DD``) compare lexicographically in the same
    order as calendar dates, so the plain ``start <= orderdate_utc <= end``
    test matches the SQL ``BETWEEN '...' AND '...'`` semantics, including both
    boundary days.

    Args:
        sales: Sales row dicts with an ``orderdate_utc`` ISO date string.
        start: Inclusive lower bound (ISO date string).
        end: Inclusive upper bound (ISO date string).

    Returns:
        The subset of ``sales`` dated within ``[start, end]``.
    """
    return [row for row in sales if start <= row["orderdate_utc"] <= end]


def aggregate_daily(sales: list[dict]) -> dict[tuple, int]:
    """Sum the sales quantity per ``(sku_id, orderdate_utc)``.

    Args:
        sales: Deduplicated, in-period sales row dicts.

    Returns:
        A dict mapping ``(sku_id, orderdate_utc)`` to the summed integer quantity.
    """
    totals: dict[tuple, int] = defaultdict(int)
    for row in sales:
        totals[(row["sku_id"], row["orderdate_utc"])] += row["sales"]
    return dict(totals)


def build_calendar(period_start: str, period_end: str) -> list[str]:
    """Build the inclusive list of ISO day strings between the bounds.

    The day count is derived dynamically from the bounds with :mod:`datetime`
    (iterating one day at a time), so the calendar length is **not** hard-coded
    to 31 — it adapts to whatever Reporting_Period is supplied.

    Args:
        period_start: Inclusive first day (ISO date string ``YYYY-MM-DD``).
        period_end: Inclusive last day (ISO date string ``YYYY-MM-DD``).

    Returns:
        A list of ISO date strings from ``period_start`` to ``period_end``
        inclusive, in ascending order. Empty if ``period_start > period_end``.
    """
    start = date.fromisoformat(period_start)
    end = date.fromisoformat(period_end)
    calendar: list[str] = []
    current = start
    while current <= end:
        calendar.append(current.isoformat())
        current += timedelta(days=1)
    return calendar


def build_grid(products: list[dict],
               calendar: list[str],
               daily: dict[tuple, int]) -> list[dict]:
    """Emit one zero-filled cell per ``(product, day)`` combination.

    Iterates ``itertools.product(products, calendar)`` — the standard-library
    analogue of the SQL ``CROSS JOIN`` — and looks up the aggregated quantity
    for each cell, defaulting missing cells to ``0`` (the zero-fill that the SQL
    ``LEFT JOIN`` + ``COALESCE`` provides).

    Args:
        products: Product row dicts with ``sku_id`` (int) and ``price`` (float).
        calendar: ISO day strings for the Reporting_Period.
        daily: Aggregated quantities keyed by ``(sku_id, orderdate_utc)``.

    Returns:
        Intermediate cell dicts with keys ``sku_id`` (int), ``date_id`` (str),
        ``price`` (float), and ``sales`` (int, zero-filled).
    """
    grid: list[dict] = []
    for product, day in itertools.product(products, calendar):
        sku_id = product["sku_id"]
        grid.append(
            {
                "sku_id": sku_id,
                "date_id": day,
                "price": product["price"],
                "sales": daily.get((sku_id, day), 0),
            }
        )
    return grid


def compute_revenue(grid: list[dict]) -> list[dict]:
    """Compute ``revenue = price * sales`` and render ``sku_id`` as a string.

    ``sku_id`` is rendered with ``str(int_value)`` so it is the canonical
    digits-only decimal string (``"795220"``, never ``"795220.0"``), matching
    the SQL ``CAST(p.sku_id AS TEXT)``. ``revenue`` is a single IEEE-754 double
    multiplication, identical to the SQL ``price * sales`` expression.

    Args:
        grid: Intermediate cell dicts from :func:`build_grid` (``sku_id`` int).

    Returns:
        Final row dicts with keys ``sku_id`` (str), ``date_id`` (str), ``price``
        (float), ``sales`` (int), ``revenue`` (float).
    """
    rows: list[dict] = []
    for cell in grid:
        sales = cell["sales"]
        price = cell["price"]
        rows.append(
            {
                "sku_id": str(cell["sku_id"]),
                "date_id": cell["date_id"],
                "price": price,
                "sales": sales,
                "revenue": price * sales,
            }
        )
    return rows


def transform(products: list[dict],
              sales: list[dict],
              period_start: str = PERIOD_START,
              period_end: str = PERIOD_END) -> list[dict]:
    """Build the dense ``revenue`` rows from extracted products and sales.

    Runs the full standard-library pipeline — dedup, period filter, daily
    aggregation, dense product x day grid with zero-fill, and revenue
    computation — and returns the rows ordered by ``(sku_id, date_id)`` using
    the rendered string ``sku_id`` (consistent with the SQL_Solution's TEXT
    ordering on read-back).

    Args:
        products: Product row dicts from :func:`extract.read_products`.
        sales: Sales row dicts from :func:`extract.read_sales`.
        period_start: Inclusive Reporting_Period start (ISO date string).
        period_end: Inclusive Reporting_Period end (ISO date string).

    Returns:
        A list of row dicts with keys ``[sku_id (str), date_id (str),
        price (float), sales (int), revenue (float)]`` — one row per
        ``(product, day)`` over the period, ordered by ``(sku_id, date_id)``.
    """
    deduped = deduplicate(sales)
    in_period = filter_period(deduped, period_start, period_end)
    daily = aggregate_daily(in_period)
    calendar = build_calendar(period_start, period_end)
    grid = build_grid(products, calendar, daily)
    rows = compute_revenue(grid)
    rows.sort(key=lambda row: (row["sku_id"], row["date_id"]))
    return rows
