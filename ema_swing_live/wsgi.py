"""WSGI entrypoint for gunicorn."""

from ema_swing_live.app import create_app


app = create_app()

