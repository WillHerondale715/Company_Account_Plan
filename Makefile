.PHONY: setup run api docker

setup:
\tpython -m venv .venv && . .venv/Scripts/activate && pip install -r requirements.txt

run:
\tstreamlit run ui/app_streamlit.py

api:
\tuvicorn src.app:app --reload --port 8000

docker:
\tdocker build -t account-plan-agent:latest .
\tdocker run --rm -p 8501:8501 --env-file .env account-plan-agent:latest
