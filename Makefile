PYTHON ?= python3
VENV_PYTHON := .venv/bin/python
.PHONY: set-up test run

set-up:
        $(PYTHON) -m venv .venv
        $(VENV_PYTHON) -m pip install -r requirements-lock.txt

test:
        $(VENV_PYTHON) z-m unittest discover -s tests -p 'test_*.py' -v

run:
        $(VENV_PYTHON) -m flask --app app run --port 5050