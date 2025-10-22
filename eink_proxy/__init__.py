"""Application package exports."""

from .app import create_app
from . import infrastructure, processing

# Expose a WSGI application instance so Gunicorn can import ``eink_proxy:app``.
app = create_app()

__all__ = ["app", "create_app", "infrastructure", "processing"]
