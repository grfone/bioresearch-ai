.PHONY: install backend frontend run test test-frontend build-frontend

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


# Run the frontend type-check + production build.
test-frontend:
	cd frontend && npm run build


# Build the production frontend bundle into `frontend/dist/`.
build-frontend:
	cd frontend && npm run build
