PYTHON ?= python3
PIP ?= pip3

.PHONY: install dev lint test clean

install:
	$(PIP) install -e .

dev:
	$(PIP) install -e ".[dev]"

lint:
	ruff check src/ tests/
	mypy src/

test:
	pytest tests/ -v --tb=short

clean:
	rm -rf dist/ build/ *.egg-info .mypy_cache .pytest_cache .ruff_cache
