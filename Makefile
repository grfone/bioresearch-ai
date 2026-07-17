.PHONY: install backend frontend run

install:
	pip install -r requirements.txt
	cd frontend && npm install


backend:
	uvicorn main:app --reload --host 0.0.0.0 --port 8000


frontend:
	cd frontend && npm run dev


run:
	make backend & make frontend