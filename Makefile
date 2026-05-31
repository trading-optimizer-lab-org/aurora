.PHONY: help count-tests test lint format coverage docs docs-clean \
	property-thorough mutate mutate-results mutate-full setup \
	precommit-install precommit-run mypy security-scan

# `make` invokes every target through $(PYTHON). Default is plain
# `python`; override when your shell's `python` is a fresh interpreter
# without the project deps installed.
#
# Quickstart on a clean machine:
#
#   1. Install the package + dev / extras under the SAME interpreter
#      you are going to run tests with:
#
#        $(PYTHON) -m pip install -e ".[dev,ga,docs,mutate]"
#
#   2. Run any target with that interpreter:
#
#        make test PYTHON=path/to/that/python
#
# A bare `make test` with the wrong PYTHON will look fine but fail
# inside subprocess-launching tests (mutmut, CLI smoke tests) because
# `sys.executable` for those subprocesses points at the bare interpreter
# without the project installed. Always install editable first.
PYTHON ?= python

help:
	@echo "Targets:"
	@echo "  setup             Install editable + dev/ga/docs/mutate extras under \$$(PYTHON)"
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
	@echo "First-time install (use the SAME interpreter you will run tests with):"
	@echo "  make setup PYTHON=path/to/python"
	@echo ""
	@echo "Then override per target if needed:"
	@echo "  make test PYTHON=path/to/python"

setup:
	$(PYTHON) -m pip install -e ".[dev,ga,docs,mutate]"

count-tests:
	@$(PYTHON) -m pytest --collect-only --quiet 2>/dev/null | grep -E '^[0-9]+ tests?' | tail -n1

test:
	$(PYTHON) -m pytest -v -m "not slow and not integration"

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

coverage:
	$(PYTHON) -m pytest --cov=aurora --cov-report=term-missing --cov-config=.coveragerc -m "not slow and not integration"

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
	NUMBA_DISABLE_JIT=1 $(PYTHON) -m mutmut run

precommit-install:
	$(PYTHON) -m pre_commit install --hook-type pre-commit --hook-type pre-push

precommit-run:
	$(PYTHON) -m pre_commit run --all-files

mypy:
	$(PYTHON) -m mypy .

security-scan:
	$(PYTHON) -m pip install bandit pip-audit
	$(PYTHON) -m bandit -r . -x tests,docs,build || true
	$(PYTHON) -m pip_audit || true
