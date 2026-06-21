"""Extract_Module: read the Source_CSV files into plain Python row dicts.

This is the Extract step of the CSV-sourced, standard-library Python_Solution.
It reads ``fw/product.csv`` and ``fw/sales.csv`` with the standard :mod:`csv`
module only — there is **no Apache Airflow import and no pandas**, so the module
is importable and runnable in a plain CPython environment.

Type handling (the ``795220.0`` trap, sidestepped structurally)
---------------------------------------------------------------
``sku_id`` and ``sales`` are parsed to Python ``int`` and ``price`` to ``float``
at read time. Because ``sku_id`` is an integer from the very start it can never
be coerced to a float, so rendering it later as ``str(sku_id)`` yields the
canonical ``"795220"`` and never ``"795220.0"``. There is no float-inference
dtype trap to defend against because the standard ``csv`` reader hands us plain
strings that we convert explicitly.

Error handling
--------------
If a Source_CSV file is missing/unreadable, or a field fails to parse, the
reader raises a descriptive ``FileNotFoundError``/``ValueError`` that names the
offending file (and field). This happens during extract, before any database
write, so a bad input never produces a partial Revenue_Table.
"""

from __future__ import annotations

import csv
from pathlib import Path

from config import PRODUCT_CSV, SALES_CSV

# Expected CSV headers, used to validate that the file is the file we expect
# and to produce a descriptive error when a column is missing.
_PRODUCT_FIELDS = ("sku_id", "sku_description", "price", "insert_timestamp_utc")
_SALES_FIELDS = (
    "sku_id",
    "order_id",
    "sales",
    "orderdate_utc",
    "insert_timestamp_utc",
)


def _open_dict_reader(path: Path, expected_fields: tuple[str, ...]):
    """Open ``path`` and return ``(file_handle, csv.DictReader)``.

    Raises a descriptive :class:`FileNotFoundError` naming ``path`` if the file
    does not exist, and a descriptive :class:`ValueError` naming ``path`` if the
    file cannot be read or is missing one of ``expected_fields``.

    The caller is responsible for closing the returned file handle.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Source CSV not found: {path}")

    try:
        handle = open(path, newline="", encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Source CSV could not be read: {path} ({exc})") from exc

    reader = csv.DictReader(handle)
    missing = [field for field in expected_fields if field not in (reader.fieldnames or [])]
    if missing:
        handle.close()
        raise ValueError(
            f"Source CSV {path} is missing required column(s): {', '.join(missing)}"
        )
    return handle, reader


def _parse_int(value: str, *, field: str, path: Path, line: int) -> int:
    """Parse ``value`` to ``int`` or raise a descriptive ValueError naming the file."""
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Source CSV {path}, line {line}: could not parse {field!r} "
            f"value {value!r} as an integer"
        ) from exc


def _parse_float(value: str, *, field: str, path: Path, line: int) -> float:
    """Parse ``value`` to ``float`` or raise a descriptive ValueError naming the file."""
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Source CSV {path}, line {line}: could not parse {field!r} "
            f"value {value!r} as a float"
        ) from exc


def read_products(path: Path = PRODUCT_CSV) -> list[dict]:
    """Read ``product.csv`` into a list of row dicts.

    Each dict has keys ``sku_id`` (int), ``sku_description`` (str), ``price``
    (float), and ``insert_timestamp_utc`` (str). ``sku_id`` is parsed straight
    to ``int`` so it never passes through a float.

    Args:
        path: Path to the product CSV. Defaults to :data:`config.PRODUCT_CSV`.

    Returns:
        List of product row dicts in file order.

    Raises:
        FileNotFoundError: If ``path`` does not exist (message names ``path``).
        ValueError: If ``path`` is unreadable, missing a required column, or a
            field fails to parse (message names ``path`` and the field).
    """
    path = Path(path)
    handle, reader = _open_dict_reader(path, _PRODUCT_FIELDS)
    try:
        products: list[dict] = []
        for row in reader:
            line = reader.line_num
            products.append(
                {
                    "sku_id": _parse_int(
                        row["sku_id"], field="sku_id", path=path, line=line
                    ),
                    "sku_description": row["sku_description"],
                    "price": _parse_float(
                        row["price"], field="price", path=path, line=line
                    ),
                    "insert_timestamp_utc": row["insert_timestamp_utc"],
                }
            )
    finally:
        handle.close()
    return products


def read_sales(path: Path = SALES_CSV) -> list[dict]:
    """Read ``sales.csv`` into a list of row dicts.

    Each dict has keys ``sku_id`` (int), ``order_id`` (str), ``sales`` (int),
    ``orderdate_utc`` (str), and ``insert_timestamp_utc`` (str). ``sku_id`` and
    ``sales`` are parsed straight to ``int``.

    Args:
        path: Path to the sales CSV. Defaults to :data:`config.SALES_CSV`.

    Returns:
        List of sales row dicts in file order.

    Raises:
        FileNotFoundError: If ``path`` does not exist (message names ``path``).
        ValueError: If ``path`` is unreadable, missing a required column, or a
            field fails to parse (message names ``path`` and the field).
    """
    path = Path(path)
    handle, reader = _open_dict_reader(path, _SALES_FIELDS)
    try:
        sales: list[dict] = []
        for row in reader:
            line = reader.line_num
            sales.append(
                {
                    "sku_id": _parse_int(
                        row["sku_id"], field="sku_id", path=path, line=line
                    ),
                    "order_id": row["order_id"],
                    "sales": _parse_int(
                        row["sales"], field="sales", path=path, line=line
                    ),
                    "orderdate_utc": row["orderdate_utc"],
                    "insert_timestamp_utc": row["insert_timestamp_utc"],
                }
            )
    finally:
        handle.close()
    return sales


def extract(
    product_csv: Path = PRODUCT_CSV,
    sales_csv: Path = SALES_CSV,
) -> tuple[list[dict], list[dict]]:
    """Read both Source_CSV files and return ``(products, sales)``.

    Convenience wrapper used by the Standalone_Runner. Reads products first,
    then sales; either read raises a descriptive error naming the offending
    file before any downstream transform/load runs.

    Args:
        product_csv: Path to the product CSV. Defaults to :data:`config.PRODUCT_CSV`.
        sales_csv: Path to the sales CSV. Defaults to :data:`config.SALES_CSV`.

    Returns:
        A ``(products, sales)`` tuple of row-dict lists.
    """
    products = read_products(product_csv)
    sales = read_sales(sales_csv)
    return products, sales
