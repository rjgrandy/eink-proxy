from __future__ import annotations

import io
import time
from typing import Callable

import requests
from PIL import Image

from .config import SETTINGS


SessionFactory = Callable[[], requests.Session]


class SourceFetcher:
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory = session_factory or requests.Session
        self._session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = self._session_factory()
        session.headers.update({"User-Agent": "eink-proxy/2.7"})
        return session

    def fetch_source(self) -> Image.Image:
        last_exception: Exception | None = None
        for attempt in range(1, SETTINGS.retries + 2):
            try:
                response = self._session.get(SETTINGS.source_url, timeout=SETTINGS.timeout)
                response.raise_for_status()
                return Image.open(io.BytesIO(response.content)).convert("RGB")
            except Exception as exc:  # pragma: no cover - network failures handled at runtime
                last_exception = exc
                time.sleep(0.4 * attempt)
        raise RuntimeError(last_exception)


FETCHER = SourceFetcher()
