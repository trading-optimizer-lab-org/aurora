.PHONY: help count-tests test lint format coverage

help:
	@echo "Targets:"
	@echo "  count-tests   Print the number of tests pytest would collect"
	@echo "  test          Run the fast test suite (-m 'not slow and not integration')"
	@echo "  lint          Run ruff check"
	@echo "  format        Run ruff format"
	@echo "  coverage      Run tests with coverage report"

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
