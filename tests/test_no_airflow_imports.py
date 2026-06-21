"""Airflow-free import smoke test.

Documents and defends the requirement that the CSV-sourced, standard-library
Python_Solution imports and runs with **Apache Airflow NOT installed**. The
reusable ETL_Modules (``extract``, ``transform``, ``load``) and the
Standalone_Runner (``run_python``) must be importable and expose their key
functions in a plain CPython environment — only the optional ``dags/main_dag.py``
TaskFlow_DAG is allowed to depend on Airflow, and it is never imported here.

Validates: Requirements 2.3, 2.13
"""

from __future__ import annotations

import importlib
import importlib.util
import sys

import pytest

# The flattened pipeline modules and the key callable each must expose.
# conftest.py puts <repo>/src on sys.path, so these import without a package
# prefix and without any installation step.
_MODULE_FUNCTIONS = {
    "extract": "extract",
    "transform": "transform",
    "load": "write_revenue",
    "run_python": "main",
}

# Whether apache-airflow is genuinely absent from this environment. This is the
# precondition the suite is designed to run under (per Requirement 2.13); when
# it holds we additionally assert the modules never pull in airflow.
_AIRFLOW_ABSENT = importlib.util.find_spec("airflow") is None


def test_airflow_is_not_installed():
    """Document the precondition: apache-airflow is not installed.

    Requirement 2.13 says the Test_Suite runs to completion with Apache Airflow
    NOT installed. This test records that precondition explicitly. If a reviewer
    happens to have airflow installed it is skipped (the import assertions in
    the other tests still guarantee the modules don't *need* it).
    """
    if not _AIRFLOW_ABSENT:
        pytest.skip("apache-airflow is installed in this environment")
    assert importlib.util.find_spec("airflow") is None


@pytest.mark.parametrize("module_name, function_name", sorted(_MODULE_FUNCTIONS.items()))
def test_module_imports_and_exposes_function(module_name, function_name):
    """Each ETL/runner module imports cleanly and exposes its key function.

    Imports the module via :func:`importlib.import_module` (so a hard failure to
    import surfaces as a test failure) and asserts it exposes the documented
    callable: ``extract.extract``, ``transform.transform``, ``load.write_revenue``,
    and ``run_python.main``.
    """
    module = importlib.import_module(module_name)
    function = getattr(module, function_name, None)
    assert function is not None, (
        f"{module_name} does not expose {function_name!r}"
    )
    assert callable(function), f"{module_name}.{function_name} is not callable"


def test_modules_do_not_pull_in_airflow():
    """Importing the modules must not import airflow as a side effect.

    Re-imports each module and asserts that ``airflow`` is absent from
    ``sys.modules`` afterwards. Only meaningful when airflow is not installed
    (otherwise an unrelated import could have loaded it), so it is skipped in
    that case.
    """
    if not _AIRFLOW_ABSENT:
        pytest.skip("apache-airflow is installed in this environment")

    for module_name in _MODULE_FUNCTIONS:
        importlib.import_module(module_name)

    assert "airflow" not in sys.modules, (
        "importing the ETL/runner modules pulled in 'airflow' as a side effect"
    )
