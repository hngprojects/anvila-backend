import pytest
from unittest.mock import AsyncMock, MagicMock
from redis.exceptions import LockError
from app.core.cache import CacheNamespace, normalize_key, clear_all_cache


async def async_iter(items):
    for item in items:
        yield item


@pytest.fixture
def ns():
    return CacheNamespace("test", default_ttl=60)


def test_normalize_key_string_passthrough():
    assert normalize_key("my-key") == "my-key"


def test_normalize_key_dict_is_hashed():
    result = normalize_key({"b": 2, "a": 1})
    assert isinstance(result, str)
    assert len(result) == 32


def test_normalize_key_dict_is_stable():
    assert normalize_key({"a": 1, "b": 2}) == normalize_key({"b": 2, "a": 1})


def test_normalize_key_different_dicts_differ():
    assert normalize_key({"a": 1}) != normalize_key({"a": 2})


# NOTE: every operation that builds key gets version first
# which is a hidden redis call. It needs to be accouted for when mocking side_effect

# --- get ---


@pytest.mark.asyncio
async def test_get_returns_none_on_miss(ns, mock_redis_client):
    mock_redis_client.get = AsyncMock(return_value=None)
    assert await ns.get("missing") is None


@pytest.mark.asyncio
async def test_get_returns_deserialized_value(ns, mock_redis_client):
    # first call is _version(), second is the actual get()
    mock_redis_client.get = AsyncMock(side_effect=[b"0", b'{"name": "ada"}'])
    assert await ns.get("user") == {"name": "ada"}


@pytest.mark.asyncio
async def test_get_returns_none_on_exception(ns, mock_redis_client):
    mock_redis_client.get = AsyncMock(side_effect=[b"0", Exception("Redis down")])
    assert await ns.get("key") is None


# --- set ---


@pytest.mark.asyncio
async def test_set_returns_true_on_success(ns, mock_redis_client):
    mock_redis_client.get = AsyncMock(return_value=b"0")  # version
    assert await ns.set("key", {"x": 1}) is True
    mock_redis_client.set.assert_called_once()


@pytest.mark.asyncio
async def test_set_uses_default_ttl(ns, mock_redis_client):
    mock_redis_client.get = AsyncMock(return_value=b"0")
    await ns.set("key", "value")
    _, kwargs = mock_redis_client.set.call_args
    assert kwargs["ex"] == 60


@pytest.mark.asyncio
async def test_set_uses_custom_ttl(ns, mock_redis_client):
    mock_redis_client.get = AsyncMock(return_value=b"0")
    await ns.set("key", "value", ttl=999)
    _, kwargs = mock_redis_client.set.call_args
    assert kwargs["ex"] == 999


@pytest.mark.asyncio
async def test_set_returns_false_on_exception(ns, mock_redis_client):
    mock_redis_client.get = AsyncMock(return_value=b"0")
    mock_redis_client.set = AsyncMock(side_effect=Exception("Redis down"))
    assert await ns.set("key", "value") is False


# --- delete ---


@pytest.mark.asyncio
async def test_delete_returns_true_when_key_existed(ns, mock_redis_client):
    mock_redis_client.get = AsyncMock(return_value=b"0")
    mock_redis_client.delete = AsyncMock(return_value=1)
    assert await ns.delete("key") is True


@pytest.mark.asyncio
async def test_delete_returns_false_when_key_missing(ns, mock_redis_client):
    mock_redis_client.get = AsyncMock(return_value=b"0")
    mock_redis_client.delete = AsyncMock(return_value=0)
    assert await ns.delete("key") is False


# --- invalidate ---


@pytest.mark.asyncio
async def test_invalidate_bumps_version(ns, mock_redis_client):
    await ns.invalidate()
    mock_redis_client.incr.assert_called_once_with("cache:test:version")


@pytest.mark.asyncio
async def test_invalidate_swallows_exception(ns, mock_redis_client):
    mock_redis_client.incr = AsyncMock(side_effect=Exception("Redis down"))
    await ns.invalidate()  # should not raise


# --- get_or_set ---


@pytest.mark.asyncio
async def test_get_or_set_returns_cached_value(ns, mock_redis_client):
    mock_redis_client.get = AsyncMock(side_effect=[b"0", b'"cached"'])
    fetch_func = AsyncMock(return_value="fresh")
    assert await ns.get_or_set("key", fetch_func) == "cached"
    fetch_func.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_set_calls_fetch_on_miss(ns, mock_redis_client):
    # version, miss, version, miss (double-check inside lock)
    mock_redis_client.get = AsyncMock(side_effect=[b"0", None, b"0", None, b"0"])
    mock_redis_client.set = AsyncMock(return_value=True)
    fetch_func = AsyncMock(return_value={"fresh": True})
    result = await ns.get_or_set("key", fetch_func)
    assert result == {"fresh": True}
    fetch_func.assert_called_once()


@pytest.mark.asyncio
async def test_get_or_set_falls_back_on_lock_error(ns, mock_redis_client):
    mock_redis_client.get = AsyncMock(side_effect=[b"0", None])

    lock = AsyncMock()
    lock.__aenter__ = AsyncMock(side_effect=LockError("timeout"))
    lock.__aexit__ = AsyncMock(return_value=False)
    mock_redis_client.lock = MagicMock(return_value=lock)

    fetch_func = AsyncMock(return_value="fallback")
    assert await ns.get_or_set("key", fetch_func) == "fallback"
    fetch_func.assert_called_once()


# --- clear_all_cache ---


@pytest.mark.asyncio
async def test_clear_all_cache_deletes_all_keys(mock_redis_client):
    mock_redis_client.scan_iter = MagicMock(
        return_value=async_iter(["cache:a", "cache:b", "cache:c"])
    )
    mock_redis_client.delete = AsyncMock(return_value=1)
    deleted = await clear_all_cache()
    assert deleted == 3
    assert mock_redis_client.delete.call_count == 3


@pytest.mark.asyncio
async def test_clear_all_cache_returns_zero_on_exception(mock_redis_client):
    mock_redis_client.scan_iter = MagicMock(side_effect=Exception("Redis down"))
    assert await clear_all_cache() == 0
