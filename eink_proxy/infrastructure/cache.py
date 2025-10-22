from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

from ..config import SETTINGS


CacheEntry = Tuple[float, bytes]


class ResponseCache:
    def __init__(self) -> None:
        self._entries: Dict[str, CacheEntry] = {}

    def get(self, key: str) -> Optional[bytes]:
        entry = self._entries.get(key)
        if not entry:
            return None
        timestamp, data = entry
        if time.time() - timestamp > SETTINGS.cache_ttl:
            self._entries.pop(key, None)
            return None
        return data

    def put(self, key: str, data: bytes) -> None:
        if len(self._entries) > 16:
            oldest = min(self._entries.items(), key=lambda item: item[1][0])[0]
            self._entries.pop(oldest, None)
        self._entries[key] = (time.time(), data)


CACHE = ResponseCache()
_last_good_png: bytes = b""


def remember_last_good(data: bytes) -> None:
    global _last_good_png
    _last_good_png = data


def last_good_png() -> Optional[bytes]:
    return _last_good_png or None
