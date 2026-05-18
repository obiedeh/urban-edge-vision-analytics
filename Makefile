.PHONY: install-dev lint test typecheck demo-report validate-artifacts verify

PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip

.venv:
	python3 -m venv .venv

install-dev: .venv
	$(PIP) install -e ".[dev]"

test: .venv
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m pytest -q

lint: .venv
	$(PYTHON) -m ruff check api vision events analytics telemetry tests examples

typecheck: .venv
	$(PYTHON) -m mypy api vision events analytics telemetry

demo-report: .venv
	$(PYTHON) examples/generate_mock_report.py --output examples/mock_inference_report.json

validate-artifacts:
	test -s examples/mock_inference_report.json

verify: lint typecheck test demo-report validate-artifacts
