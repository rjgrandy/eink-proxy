import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "eink_proxy"

# Create a lightweight package structure in sys.modules so we can import the cache
# module without pulling in optional third-party dependencies (Flask, requests, PIL).
eink_proxy_pkg = types.ModuleType("eink_proxy")
eink_proxy_pkg.__path__ = [str(PACKAGE_ROOT)]
sys.modules.setdefault("eink_proxy", eink_proxy_pkg)

config_spec = importlib.util.spec_from_file_location(
    "eink_proxy.config", PACKAGE_ROOT / "config.py"
)
config_module = importlib.util.module_from_spec(config_spec)
sys.modules.setdefault("eink_proxy.config", config_module)
assert config_spec.loader is not None
config_spec.loader.exec_module(config_module)

infrastructure_pkg = types.ModuleType("eink_proxy.infrastructure")
infrastructure_pkg.__path__ = [str(PACKAGE_ROOT / "infrastructure")]
sys.modules.setdefault("eink_proxy.infrastructure", infrastructure_pkg)

cache_spec = importlib.util.spec_from_file_location(
    "eink_proxy.infrastructure.cache",
    PACKAGE_ROOT / "infrastructure" / "cache.py",
)
cache_module = importlib.util.module_from_spec(cache_spec)
sys.modules.setdefault("eink_proxy.infrastructure.cache", cache_module)
assert cache_spec.loader is not None
cache_spec.loader.exec_module(cache_module)

ResponseCache = cache_module.ResponseCache


def test_response_cache_eviction_limit():
    cache = ResponseCache()

    # Fill the cache beyond the limit to trigger eviction logic.
    for idx in range(20):
        cache.put(f"key-{idx}", b"data")

    assert len(cache._entries) == 16

    # Ensure the oldest entries are evicted first
    assert "key-0" not in cache._entries
    assert "key-3" not in cache._entries
    assert "key-4" in cache._entries
