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
from custom_components.comfortzone_serial.telemetry.decoder import EX35_TEMPERATURE_KEYS
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
    assert len(enabled) == 9
    ids = {
        entity.unique_id.removeprefix(entry.entry_id + "_"): entity.entity_id
        for entity in enabled
    }
    assert set(ids) == set(EX35_TEMPERATURE_KEYS)
    assert all(hass.states.get(id).state == STATE_UNAVAILABLE for id in ids.values())
    chunks = datagrams("standalone-split-reply.hex")
    receive(coordinator, chunks[0])
    assert hass.states.get(ids["hot_water_temperature"]).state == STATE_UNAVAILABLE
    receive(coordinator, chunks[1])
    assert all(hass.states.get(id).state != STATE_UNAVAILABLE for id in ids.values())
    assert hass.states.get(ids["hot_water_temperature"]).state == "49.6"
    assert hass.states.get(ids["indoor_temperature"]).state == "22.0"
    await advance(hass, freezer, 15)
    assert len(transport.sent) == 2
    invalid = bytearray(b"".join(chunks))
    invalid[124:126] = (-990).to_bytes(2, "little", signed=True)
    invalid[78:80] = (-990).to_bytes(2, "little", signed=True)
    receive(coordinator, corrected(invalid).raw)
    assert hass.states.get(ids["hot_water_temperature"]).state == STATE_UNAVAILABLE
    assert hass.states.get(ids["flow_water_temperature"]).state == STATE_UNAVAILABLE
    assert hass.states.get(ids["outdoor_temperature"]).state == "12.4"
    await advance(hass, freezer, 21)
    assert all(hass.states.get(id).state == STATE_UNAVAILABLE for id in ids.values())
    diagnostic = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostic["polling_stats"]["replies_received"] == 2
    assert "layout_validation" not in diagnostic
    assert "display_confirmed_keys" not in diagnostic
    assert "192.0.2.10" not in json.dumps(diagnostic)
    poll_timer = coordinator.listener._poll_timer
    assert await hass.config_entries.async_unload(entry.entry_id)
    sent = len(transport.sent)
    await advance(hass, freezer, 60)
    assert transport.closed and poll_timer.cancelled() and len(transport.sent) == sent


async def test_ex35_passive_selection_never_sends(hass, udp_endpoint):
    entry = await setup_entry(hass, options=OPTIONS | {"polling_enabled": False})
    receive(entry.runtime_data, datagrams("standalone-reply.hex")[0])
    assert len(hass.states.async_all("sensor")) == 9
    assert all(
        state.state != STATE_UNAVAILABLE for state in hass.states.async_all("sensor")
    )


@pytest.mark.parametrize("profile", ["ex35_0b15_temperatures_v1", "observe_only"])
@pytest.mark.parametrize("disable_new", [False, True])
async def test_upgrade_enables_old_defaults_and_preserves_user_choices(
    hass, udp_endpoint, profile, disable_new
):
    entry = MockConfigEntry(
        domain=DOMAIN, data=NETWORK, options={"profile": profile},
        version=1, minor_version=1, pref_disable_new_entities=disable_new,
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    original = {}
    for key in EX35_TEMPERATURE_KEYS:
        disabled_by = (
            er.RegistryEntryDisabler.USER if key == "flow_water_temperature"
            else None if key == "indoor_temperature"
            else er.RegistryEntryDisabler.INTEGRATION
        )
        original[key] = registry.async_get_or_create(
            "sensor", DOMAIN, f"{entry.entry_id}_{key}",
            config_entry=entry, disabled_by=disabled_by,
        )
    unrelated = registry.async_get_or_create(
        "sensor", DOMAIN, f"{entry.entry_id}_unrelated",
        config_entry=entry, disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 2
    assert entry.options == {"profile": profile}
    for before in original.values():
        after = registry.async_get(before.entity_id)
        assert after.id == before.id and after.unique_id == before.unique_id
        expected = (
            None if not disable_new
            and before.disabled_by is er.RegistryEntryDisabler.INTEGRATION
            else before.disabled_by
        )
        assert after.disabled_by is expected
    assert registry.async_get(unrelated.entity_id).disabled_by is (
        er.RegistryEntryDisabler.INTEGRATION
    )
    # A later explicit user disable survives reload; the migration runs once.
    changed = original["return_water_temperature"]
    registry.async_update_entity(
        changed.entity_id, disabled_by=er.RegistryEntryDisabler.USER
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(changed.entity_id).disabled_by is (
        er.RegistryEntryDisabler.USER
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
