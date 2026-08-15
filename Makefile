.PHONY: install backend frontend run test test-frontend test-frontend-unit test-frontend-build build-frontend

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
