# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12-slim

FROM python:${PYTHON_VERSION} as runtime

# Required by Pillow and the runtime healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libjpeg62-turbo \
        libpng16-16 \
        zlib1g \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5500 \
    SOURCE_URL="http://192.168.1.199:10000/lovelace-main/einkpanelcolor?viewport=800x480" \
    WORKERS=2 \
    THREADS=2

WORKDIR /app

# Ensure we only copy the package directory
COPY eink_proxy /app/eink_proxy

# Verify the package structure exists
RUN echo "=== Verifying package structure ===" && \
    ls -la /app/ && \
    echo "--- Contents of eink_proxy directory ---" && \
    ls -la /app/eink_proxy/ && \
    test -f /app/eink_proxy/__init__.py && echo "✓ __init__.py found" || (echo "✗ __init__.py missing!" && exit 1)

RUN pip install --no-cache-dir pillow flask requests gunicorn

# Test that Python can import the app during build
RUN echo "=== Testing Python imports ===" && \
    python -c "import sys; print('Python path:', sys.path)" && \
    python -c "import eink_proxy; print('✓ Package imports')" && \
    python -c "from eink_proxy.app import app; print('✓ App object found:', type(app))"

EXPOSE 5500

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# Simplified CMD - use direct path without shell variables
CMD gunicorn --bind 0.0.0.0:5500 --workers 2 --threads 2 eink_proxy.app:app
