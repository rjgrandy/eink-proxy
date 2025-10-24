"""Application package exports."""

from .app import APP_VERSION, create_app
from . import infrastructure, processing

# Expose a WSGI application instance so Gunicorn can import ``eink_proxy:app``.
app = create_app()

__version__ = APP_VERSION

__all__ = ["APP_VERSION", "__version__", "app", "create_app", "infrastructure", "processing"]
