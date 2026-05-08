.PHONY: help count-tests test lint format coverage docs docs-clean property-thorough

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

count-tests:
	@pytest --collect-only --quiet 2>/dev/null | grep -E '^[0-9]+ tests?' | tail -n1

test:
	pytest -v -m "not slow and not integration"

lint:
	ruff check .

format:
	ruff format .

coverage:
	pytest --cov=quantforge --cov-report=term-missing --cov-config=.coveragerc -m "not slow and not integration"

docs:
	python -m sphinx -b html -q docs docs/_build/html

docs-clean:
	rm -rf docs/_build docs/api/generated

property-thorough:
	HYPOTHESIS_PROFILE=thorough pytest -v tests/test_property.py tests/test_property_v2.py

mutate:
	python -m mutmut run --paths-to-mutate=core/metrics.py

mutate-results:
	python -m mutmut results

mutate-full:
	python -m mutmut run
