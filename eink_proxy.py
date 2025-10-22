#!/usr/bin/env python3
"""Run the E-ink 7-color image proxy application."""

from eink_proxy import create_app
from eink_proxy.config import SETTINGS

app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=SETTINGS.port, debug=False)
