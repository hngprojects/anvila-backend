import pytest


@pytest.fixture(autouse=True)
async def _dispose_production_engine_between_tests():
    """Worker tests call _run_generation which opens its own AsyncSession via
    app.db.session.AsyncSessionLocal. That session's connections come from the
    module-level production engine's QueuePool. pytest-asyncio creates a fresh
    event loop per test, so any pooled connection from a previous test is bound
    to a closed loop and raises 'another operation in progress' on reuse.
    Disposing the engine before each test guarantees a clean pool."""
    from app.db.session import engine

    await engine.dispose()
    yield
    await engine.dispose()
