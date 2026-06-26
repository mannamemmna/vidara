# main.py — Entry point for gunicorn: gunicorn main:app
from app import create_app

app = create_app()
