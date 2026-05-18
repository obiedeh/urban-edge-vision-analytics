.PHONY: install-dev lint test typecheck verify

PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip

.venv:
	python3 -m venv .venv

install-dev: .venv
	$(PIP) install -e ".[dev]"

test: .venv
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m pytest -q

lint: .venv
	$(PYTHON) -m ruff check api vision events analytics telemetry tests

typecheck: .venv
	$(PYTHON) -m mypy api vision events analytics telemetry

verify: lint typecheck test
