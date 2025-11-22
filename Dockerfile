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

COPY eink_proxy /app/eink_proxy

RUN pip install --no-cache-dir pillow flask requests gunicorn

EXPOSE 5500

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

ENV APP_IMPORT_PATH=eink_proxy:app

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers ${WORKERS} --threads ${THREADS} ${APP_IMPORT_PATH}"]
