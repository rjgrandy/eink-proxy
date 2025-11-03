"""Tests for the network helper utilities."""

import pytest


pytest.importorskip("requests")

from eink_proxy.infrastructure.network import _apply_base_and_path, _merge_query_params


def test_merge_query_params_no_overrides():
    url = "http://example.com/render?dashboard=main"
    assert _merge_query_params(url, None) == url


def test_merge_query_params_overrides_existing_values():
    url = "http://example.com/render?dashboard=main&puppet=default"
    merged = _merge_query_params(url, {"dashboard": "kitchen", "puppet": "night"})
    assert (
        merged
        == "http://example.com/render?dashboard=kitchen&puppet=night"
    )


def test_merge_query_params_adds_new_keys_and_removes_none_values():
    url = "http://example.com/render"
    merged = _merge_query_params(
        url, {"dashboard": "office", "puppet": None, "theme": "dark"}
    )
    assert merged == "http://example.com/render?dashboard=office&theme=dark"


@pytest.mark.parametrize(
    "base_url, path_override, expected",
    [
        (
            "https://override.local:8123",
            None,
            "https://override.local:8123/render?dashboard=main",
        ),
        (
            "https://override.local:8123/base",
            "night",
            "https://override.local:8123/base/night?dashboard=main",
        ),
        (
            "https://override.local:8123/base/",
            "night",
            "https://override.local:8123/base/night?dashboard=main",
        ),
        (
            "https://override.local:8123/base",
            "/alt/path",
            "https://override.local:8123/alt/path?dashboard=main",
        ),
    ],
)
def test_apply_base_and_path(base_url, path_override, expected):
    url = "http://default/render?dashboard=main"
    assert (
        _apply_base_and_path(url, base_url=base_url, path_override=path_override)
        == expected
    )


def test_apply_base_and_path_with_path_override_only():
    url = "http://default/render?dashboard=main"
    assert (
        _apply_base_and_path(url, path_override="alt")
        == "http://default/alt?dashboard=main"
    )


def test_apply_base_and_path_rejects_invalid_base():
    with pytest.raises(ValueError):
        _apply_base_and_path(
            "http://default/render?dashboard=main",
            base_url="not-a-valid-base",
        )
