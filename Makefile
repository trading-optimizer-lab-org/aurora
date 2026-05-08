.PHONY: help count-tests test lint format coverage docs docs-clean \
	property-thorough mutate mutate-results mutate-full

# Override on Windows or when 'python' is a fresh interpreter without
# the project deps installed:
#   make test PYTHON="C:/Python314/python.exe"
PYTHON ?= python

help:
	@echo "Targets:"
	@echo "  count-tests       Print the number of tests pytest would collect"
	@echo "  test              Run the fast test suite (-m 'not slow and not integration')"
	@echo "  lint              Run ruff check"
	@echo "  format            Run ruff format"
	@echo "  coverage          Run tests with coverage report"
	@echo "  docs              Build the Sphinx HTML API reference"
	@echo "  docs-clean        Remove the built docs/_build/ tree"
	@echo "  property-thorough Run property tests under HYPOTHESIS_PROFILE=thorough"
	@echo "  mutate            Run mutmut against core/metrics.py"
	@echo "  mutate-results    Show mutmut survivor list"
	@echo "  mutate-full       Run the full curated mutmut sweep"
	@echo ""
	@echo "Override interpreter via: make <target> PYTHON=\"C:/Python314/python.exe\""

count-tests:
	@$(PYTHON) -m pytest --collect-only --quiet 2>/dev/null | grep -E '^[0-9]+ tests?' | tail -n1

test:
	$(PYTHON) -m pytest -v -m "not slow and not integration"

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

coverage:
	$(PYTHON) -m pytest --cov=quantforge --cov-report=term-missing --cov-config=.coveragerc -m "not slow and not integration"

docs:
	$(PYTHON) -m sphinx -b html -q docs docs/_build/html

docs-clean:
	rm -rf docs/_build docs/api/generated

property-thorough:
	HYPOTHESIS_PROFILE=thorough $(PYTHON) -m pytest -v tests/test_property.py tests/test_property_v2.py

mutate:
	$(PYTHON) -m mutmut run --paths-to-mutate=core/metrics.py

mutate-results:
	$(PYTHON) -m mutmut results

mutate-full:
	$(PYTHON) -m mutmut run
