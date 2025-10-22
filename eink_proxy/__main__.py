"""Entry point for running the E-ink proxy as a module."""

from __future__ import annotations

from .app import create_app
from .config import SETTINGS

app = create_app()


def main() -> None:
    """Run the Flask development server."""
    app.run(host="0.0.0.0", port=SETTINGS.port, debug=False)


if __name__ == "__main__":
    main()
