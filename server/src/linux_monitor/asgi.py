"""ASGI entrypoint."""

from .config import Settings
from .main import create_app

settings = Settings()
app = create_app(settings)
