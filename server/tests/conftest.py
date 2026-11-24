import os
import asyncio
import pytest

os.environ.setdefault("READER_TOKEN", "r" * 40)
os.environ.setdefault("ADMIN_TOKEN", "a" * 40)
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("HOST", "127.0.0.1")
os.environ.setdefault("PORT", "8000")


@pytest.fixture(autouse=True)
def _event_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()