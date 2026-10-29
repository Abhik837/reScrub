"""ASGI entry point: uvicorn rescrub.main:app"""

from .api import create_app

app = create_app()
