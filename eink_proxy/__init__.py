"""Application package exports."""

from .app import APP_VERSION, app, create_app
from . import infrastructure, processing

__version__ = APP_VERSION

__all__ = ["APP_VERSION", "__version__", "app", "create_app", "infrastructure", "processing"]
