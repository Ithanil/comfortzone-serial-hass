"""Captured standalone replies through HA, with fake request transmission."""

import json
from unittest.mock import patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.comfortzone_serial.const import DOMAIN, OPTION_DEFAULTS
from custom_components.comfortzone_serial.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.comfortzone_serial.telemetry.polling import temperature_request
from tests.ha.test_config_flow import NETWORK
from tests.ha.test_runtime import advance, receive, setup_entry
from tests.test_ex35 import corrected, datagrams

pytestmark = pytest.mark.asyncio
OPTIONS = {
    "profile": "ex35_0b15_temperatures_v1",
    "polling_enabled": True,
    "poll_interval": 15,
    "stale_timeout": 20,
}


async def test_ex35_polling_sensors_sentinel_freshness_and_unload(
    hass, polling_endpoint, freezer
):
    entry = await setup_entry(hass, options=OPTIONS)
    coordinator = entry.runtime_data
    transport = polling_endpoint[0]
    assert transport.sent == [(temperature_request(), (NETWORK["source_ip"], 4001))]
    registry = er.async_get(hass)
    registered = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert len(registered) == 9
    enabled = [entity for entity in registered if entity.disabled_by is None]
    assert len(enabled) == 3
    ids = {
        entity.unique_id.removeprefix(entry.entry_id + "_"): entity.entity_id
        for entity in enabled
    }
    assert set(ids) == {
        "outdoor_temperature",
        "indoor_temperature",
        "hot_water_temperature",
    }
    assert all(hass.states.get(id).state == STATE_UNAVAILABLE for id in ids.values())
    chunks = datagrams("standalone-split-reply.hex")
    receive(coordinator, chunks[0])
    assert hass.states.get(ids["hot_water_temperature"]).state == STATE_UNAVAILABLE
    receive(coordinator, chunks[1])
    assert hass.states.get(ids["hot_water_temperature"]).state == "49.6"
    assert hass.states.get(ids["indoor_temperature"]).state == "22.0"
    await advance(hass, freezer, 15)
    assert len(transport.sent) == 2
    invalid = bytearray(b"".join(chunks))
    invalid[124:126] = (-990).to_bytes(2, "little", signed=True)
    receive(coordinator, corrected(invalid).raw)
    assert hass.states.get(ids["hot_water_temperature"]).state == STATE_UNAVAILABLE
    assert hass.states.get(ids["outdoor_temperature"]).state == "12.4"
    await advance(hass, freezer, 21)
    assert all(hass.states.get(id).state == STATE_UNAVAILABLE for id in ids.values())
    diagnostic = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostic["polling_stats"]["replies_received"] == 2
    assert "192.0.2.10" not in json.dumps(diagnostic)
    poll_timer = coordinator.listener._poll_timer
    assert await hass.config_entries.async_unload(entry.entry_id)
    sent = len(transport.sent)
    await advance(hass, freezer, 60)
    assert transport.closed and poll_timer.cancelled() and len(transport.sent) == sent


async def test_ex35_passive_selection_never_sends(hass, udp_endpoint):
    entry = await setup_entry(hass, options=OPTIONS | {"polling_enabled": False})
    receive(entry.runtime_data, datagrams("standalone-reply.hex")[0])
    assert len(hass.states.async_all("sensor")) == 3
    assert all(
        state.state != STATE_UNAVAILABLE for state in hass.states.async_all("sensor")
    )


@pytest.mark.parametrize(
    "change",
    [
        {"profile": "observe_only"},
        {"profile": "czbridge_rx50_temperatures_v1"},
        {"stale_timeout": 15},
        {"partial_timeout": 10, "gap_timeout": 10},
        {"pump_address": "bad"},
    ],
)
async def test_polling_option_validation(hass, change):
    entry = MockConfigEntry(domain=DOMAIN, data=NETWORK)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], OPTION_DEFAULTS | OPTIONS | change
    )
    assert result["errors"] == {"base": "invalid_options"}


async def test_enable_polling_options_reload(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=NETWORK)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], OPTION_DEFAULTS | OPTIONS
        )
        await hass.async_block_till_done()
        reload.assert_called_once_with(entry.entry_id)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["polling_enabled"] is True
