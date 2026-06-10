# tests/conftest.py
import pytest
from unittest.mock import AsyncMock


try:
    from browser.connection import BrowserConnection
except ImportError:
    # BrowserConnection is implemented in Task 3; fixtures below are
    # only used by later tasks, so this is safe to defer.
    BrowserConnection = None


@pytest.fixture
def mock_ws():
    return AsyncMock()


@pytest.fixture
def conn(mock_ws):
    if BrowserConnection is None:
        pytest.skip("BrowserConnection not yet implemented (Task 3)")
    c = BrowserConnection()
    c.set_ws(mock_ws)
    return c
