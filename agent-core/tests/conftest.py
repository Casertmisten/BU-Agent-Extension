# tests/conftest.py
import pytest
from unittest.mock import AsyncMock


from browser.connection import BrowserConnection


@pytest.fixture
def mock_ws():
    return AsyncMock()


@pytest.fixture
def conn(mock_ws):
    c = BrowserConnection()
    c.set_ws(mock_ws)
    return c
