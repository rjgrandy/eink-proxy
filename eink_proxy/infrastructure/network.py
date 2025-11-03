from __future__ import annotations

import io
import time
import posixpath
from typing import Callable, Mapping

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from PIL import Image

from ..config import SETTINGS


SessionFactory = Callable[[], requests.Session]


def _merge_query_params(url: str, overrides: Mapping[str, str | None] | None) -> str:
    """Merge override query parameters into ``url``.

    Parameters with a value of ``None`` are removed from the query string. Values
    are treated as opaque strings; callers are responsible for providing any
    necessary encoding.
    """

    if not overrides:
        return url

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))

    for key, value in overrides.items():
        if value is None:
            query.pop(key, None)
        else:
            query[key] = value

    return urlunsplit(parts._replace(query=urlencode(query, doseq=True)))


def _normalize_base_for_join(base_path: str) -> str:
    if not base_path:
        return "/"
    return base_path if base_path.endswith("/") else f"{base_path}/"


def _resolve_relative_path(base_path: str, override_path: str) -> str:
    normalized_base = _normalize_base_for_join(base_path)
    joined = posixpath.normpath(f"{normalized_base}{override_path}")
    return joined if joined.startswith("/") else f"/{joined}"


def _apply_base_and_path(
    url: str,
    *,
    base_url: str | None = None,
    path_override: str | None = None,
) -> str:
    if not base_url and path_override is None:
        return url

    parts = urlsplit(url)
    path_to_use = path_override if path_override is not None else parts.path

    if base_url:
        base_parts = urlsplit(base_url)
        if not base_parts.scheme or not base_parts.netloc:
            raise ValueError(f"Invalid source_base override: {base_url}")

        if path_to_use and not path_to_use.startswith("/") and base_parts.path:
            new_path = _resolve_relative_path(base_parts.path, path_to_use)
        elif path_to_use and not path_to_use.startswith("/"):
            new_path = _resolve_relative_path("/", path_to_use)
        else:
            new_path = path_to_use or base_parts.path

        combined = base_parts._replace(path=new_path or "", query=parts.query, fragment=parts.fragment)
        return urlunsplit(combined)

    if path_override is not None:
        updated = parts._replace(path=path_to_use)
        return urlunsplit(updated)

    return url


class SourceFetcher:
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory = session_factory or requests.Session
        self._session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = self._session_factory()
        session.headers.update({"User-Agent": "eink-proxy/2.7"})
        return session

    def fetch_source(
        self,
        *,
        source_url: str | None = None,
        base_url: str | None = None,
        path: str | None = None,
        overrides: Mapping[str, str | None] | None = None,
    ) -> Image.Image:
        last_exception: Exception | None = None
        for attempt in range(1, SETTINGS.retries + 2):
            try:
                target_url = source_url or SETTINGS.source_url
                target_url = _apply_base_and_path(
                    target_url,
                    base_url=base_url,
                    path_override=path,
                )
                target_url = _merge_query_params(target_url, overrides)
                response = self._session.get(target_url, timeout=SETTINGS.timeout)
                response.raise_for_status()
                return Image.open(io.BytesIO(response.content)).convert("RGB")
            except Exception as exc:  # pragma: no cover - network failures handled at runtime
                last_exception = exc
                time.sleep(0.4 * attempt)
        raise RuntimeError(last_exception)


FETCHER = SourceFetcher()
