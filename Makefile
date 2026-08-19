.PHONY: install backend frontend run test test-frontend test-frontend-unit test-frontend-build build-frontend verify verify-no-color verify-ci verify-ci-no-color

install:
	pip install -r requirements.txt
	cd frontend && npm install


backend:
	uvicorn main:app --reload --host 0.0.0.0 --port 8000


frontend:
	cd frontend && npm run dev


run:
	make backend & make frontend


# Run the Python test suite (FSM + citation validator + orchestrator + FastAPI integration).
test:
	PYTHONPATH=. .venv/bin/python -m pytest tests/ -v


# Run the frontend Vitest suite (component tests for hooks, panels, etc.).
#
# Requires ``npm install`` first. The frontend test environment is jsdom —
# we test React components, hooks, and any client-side logic that benefits
# from a real DOM. Source-level greps live in tests/unit too, but Vitest is
# the dedicated runner for things that touch React state.
#
# Run from the project root:
#   make test-frontend
#
# Or directly for watch mode:
#   cd frontend && npm run test:watch
test-frontend: test-frontend-unit test-frontend-build


# Run only the Vitest unit / component tests (no type-check, no build).
test-frontend-unit:
	cd frontend && npm test


# Run only the TypeScript type-check + production build.
test-frontend-build:
	cd frontend && npm run build


# Build the production frontend bundle into `frontend/dist/`.
build-frontend:
	cd frontend && npm run build


# End-to-end smoke test -- builds the Docker image, boots
# the container, exercises every /admin/* endpoint plus a
# functional workspace + DOI fetch, then tears down.
#
# This is the "test the whole bootstrap and make sure it
# runs from the beginning to the end without hiccups"
# target -- the scriptable equivalent of the manual
# live-verify pattern I've been running session by session.
#
# Requires: bash, curl, jq, docker, python3 -- all checked
# at script start with helpful install instructions if
# anything is missing.
#
# Set NO_COLOR=1 to disable ANSI color output (useful for
# CI logs that don't interpret escape codes).
verify:
	./scripts/verify.sh


# Same as ``verify`` but suppresses the ANSI color output
# for clean log capture in CI or shell recording.
verify-no-color:
	NO_COLOR=1 ./scripts/verify.sh


# Same as ``verify`` but assumes the container is already
# running. Does NOT build, start, or tear down -- just hits
# /health + runs the admin endpoint smoke tests.
#
# Designed for CI workflows where another step has already
# started the container, and for cheap local re-runs after
# ``make verify`` has already done the bootstrap. Useful
# when you've made a small code change and want to
# re-validate the admin endpoints without rebuilding
# the whole image.
#
# Same shared library as ``verify`` -- both scripts run
# the same checks against the same admin endpoints.
verify-ci:
	./scripts/verify-ci.sh


# Same as ``verify-ci`` but suppresses ANSI color output
# for clean log capture.
verify-ci-no-color:
	NO_COLOR=1 ./scripts/verify-ci.sh
