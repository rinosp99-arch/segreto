"""Shared pytest configuration: ONE session-scoped asyncio loop for every async test.

motor binds its connection pool to the loop that first touches it, so all async tests (Phase 11 health
reconciliation, Phase 12 capabilities, ...) must run on the same loop whether executed alone or combined.
"""
import pytest


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
async def _session_loop(anyio_backend):
    """Keeps the anyio session runner (and therefore the event loop) alive for the whole pytest session and purges
    harness residue (revoked test keys, soft-deleted test entities) when the session ends."""
    yield
    import sys
    sys.path.insert(0, "/app/tests")
    from _cleanup import purge_test_residue_async
    await purge_test_residue_async()
