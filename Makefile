# Makefile for Oneiric test execution patterns

.PHONY: help test test-fast test-slow test-unit test-integration test-security test-all test-analyze

help:  ## Show this help message
	@echo "Oneiric Test Execution Targets:"
	@echo "================================"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

test:  ## Run all tests (default: 10min timeout)
	uv run pytest -v

test-fast:  ## Run only fast tests (<1s per test)
	uv run pytest -m "fast" -v

test-slow:  ## Run only slow tests (>5s per test)
	uv run pytest -m "slow" -v

test-not-slow:  ## Run all tests except slow ones (good for quick CI)
	uv run pytest -m "not slow" -v

test-unit:  ## Run only unit tests (isolated, no I/O)
	uv run pytest -m "unit" -v

test-integration:  ## Run integration and e2e tests
	uv run pytest -m "integration or e2e" -v

test-security:  ## Run security-related tests
	uv run pytest -m "security" -v

test-adapter:  ## Run adapter-specific tests
	uv run pytest -m "adapter" -v

test-remote:  ## Run remote manifest tests
	uv run pytest -m "remote" -v

test-runtime:  ## Run runtime orchestration tests
	uv run pytest -m "runtime" -v

test-all:  ## Run all tests with detailed timing analysis
	uv run pytest --durations=20 -v

test-analyze:  ## Run tests and analyze timing distribution
	uv run pytest --durations=0 --tb=no -q 2>&1 | tee test_output.txt
	uv run python scripts/analyze_test_timings.py test_output.txt

test-coverage:  ## Run tests with coverage report
	uv run pytest --cov=oneiric --cov-report=html --cov-report=term-missing

test-parallel:  ## Run tests in parallel (auto-detect workers)
	uv run pytest -n auto -v

test-quick:  ## Quick test run (fast tests only, no coverage)
	uv run pytest -m "fast" --no-cov -v

crackerjack:  ## Run crackerjack quality suite
	python -m crackerjack

crackerjack-test:  ## Run crackerjack with tests
	python -m crackerjack -t

crackerjack-verbose:  ## Run crackerjack with verbose output
	python -m crackerjack -t -v
