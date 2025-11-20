from eink_proxy.app import resolve_source_url
from eink_proxy.config import SETTINGS


def test_resolve_source_url_defaults_to_settings() -> None:
    assert resolve_source_url({}) == SETTINGS.source_url


def test_resolve_source_url_accepts_direct_override() -> None:
    override = "http://example.com/image.png"
    assert resolve_source_url({"source_url": override}) == override


def test_resolve_source_url_builds_from_base_and_path() -> None:
    args = {"source_base": "http://foo:1234", "source_path": "abc/def.png"}

    assert resolve_source_url(args) == "http://foo:1234/abc/def.png"


def test_resolve_source_url_handles_slashes_gracefully() -> None:
    args = {"source_base": "http://foo:1234/", "source_path": "/abc/def.png"}

    assert resolve_source_url(args) == "http://foo:1234/abc/def.png"
