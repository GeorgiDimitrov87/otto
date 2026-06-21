.PHONY: env run run-sql run-python test

env:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

run: run-sql run-python

run-sql:
	PYTHONPATH=src .venv/bin/python -m sql_runner

run-python:
	PYTHONPATH=src .venv/bin/python -m run_python

test:
	PYTHONPATH=src .venv/bin/python -m pytest
