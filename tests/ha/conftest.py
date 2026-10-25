"""Real HA platform with a receive-only fake transport; no pump or LAN access."""

import asyncio
from unittest.mock import patch

import pytest

from tests.test_udp import FakeTransport


@pytest.fixture(autouse=True)
def custom_integration(enable_custom_integrations):
    yield


@pytest.fixture
async def udp_endpoint(hass):
    transports = []

    async def endpoint(factory, **kwargs):
        assert "remote_addr" not in kwargs
        protocol = factory()
        transport = FakeTransport(protocol)
        transports.append(transport)
        protocol.connection_made(transport)
        return transport, protocol

    with patch.object(asyncio.get_running_loop(), "create_datagram_endpoint", endpoint):
        yield transports


@pytest.fixture
async def polling_endpoint(hass):
    from tests.test_polling import PollTransport

    transports = []

    async def endpoint(factory, **kwargs):
        protocol = factory()
        transport = PollTransport(protocol)
        transports.append(transport)
        protocol.connection_made(transport)
        return transport, protocol

    with patch.object(asyncio.get_running_loop(), "create_datagram_endpoint", endpoint):
        yield transports
