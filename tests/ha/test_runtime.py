"""Synthetic data through real HA setup, state machine and registries."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, STATE_UNAVAILABLE
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_component import async_update_entity
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.comfortzone_serial import async_unload_entry
from custom_components.comfortzone_serial.const import DOMAIN
from custom_components.comfortzone_serial.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.comfortzone_serial.telemetry.decoder import (
    TEMPERATURE_KEYS,
    DecoderProfile,
    Temperature,
    decode_frame,
)
from custom_components.comfortzone_serial.telemetry.framing import Frame
from custom_components.comfortzone_serial.telemetry.stream import Observation, Origin
from tests.fixtures import make_frame, temperature_frame

from .test_config_flow import NETWORK

pytestmark = pytest.mark.asyncio
PROFILE = DecoderProfile.CZBRIDGE_RX50


async def setup_entry(hass, *, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="ComfortZone Serial",
        data=NETWORK,
        options={"profile": PROFILE.value, "stale_timeout": 5}
        if options is None
        else options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def entity_ids(hass, entry):
    registry = er.async_get(hass)
    return {
        key: registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
        for key in TEMPERATURE_KEYS
    }


def receive(coordinator, raw=None):
    coordinator.listener.receiver.datagram_received(
        temperature_frame() if raw is None else raw, ("192.0.2.10", 4001)
    )


async def advance(hass, freezer, seconds):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, datetime.now(UTC))
    await hass.async_block_till_done()


async def test_sensors_metadata_freshness_unknown_traffic_and_recovery(
    hass, udp_endpoint, freezer
):
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    ids = entity_ids(hass, entry)
    assert len(set(ids.values())) == 8
    assert all(hass.states.get(id).state == STATE_UNAVAILABLE for id in ids.values())
    assert coordinator.update_interval is None
    receive(coordinator)
    await hass.async_block_till_done()
    outdoor = hass.states.get(ids["outdoor_temperature"])
    assert outdoor.state == "-12.5"
    assert outdoor.attributes["unit_of_measurement"] == "°C"
    assert outdoor.attributes["device_class"] == "temperature"
    assert outdoor.attributes["state_class"] == "measurement"
    assert (
        outdoor.attributes["friendly_name"] == "ComfortZone Serial Outdoor temperature"
    )
    assert "raw_hex" not in outdoor.attributes
    await advance(hass, freezer, 4)
    receive(coordinator, make_frame(register=b"\x00" * 9))
    await advance(hass, freezer, 1)
    assert all(hass.states.get(id).state == STATE_UNAVAILABLE for id in ids.values())
    receive(coordinator)
    assert hass.states.get(ids["outdoor_temperature"]).state == "-12.5"
    # update_entity does not create requests, listeners, or a second socket.
    for entity_id in ids.values():
        await async_update_entity(hass, entity_id)
    assert len(udp_endpoint) == 1
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert udp_endpoint[0].closed
    assert coordinator._expiry is None
    assert coordinator.listener._timer is None


async def test_observation_default_no_measurements_with_diagnostic_evidence(
    hass, udp_endpoint
):
    entry = await setup_entry(hass, options={})
    receive(entry.runtime_data)
    assert hass.states.async_all("sensor") == []
    diagnostic = await async_get_config_entry_diagnostics(hass, entry)
    frame = diagnostic["telemetry"]["recent_frames"][0]
    assert frame["reason"] == "observe_only"
    assert frame["raw_hex"] == temperature_frame().hex()
    assert diagnostic["receiver_stats"]["accepted"] == 1
    serialized = json.dumps(diagnostic)
    assert "192.0.2.10" not in serialized
    assert entry.runtime_data.pipeline.session_id not in serialized


async def test_reload_identity_no_restoration_and_profile_switch(hass, udp_endpoint):
    entry = await setup_entry(hass)
    ids = entity_ids(hass, entry)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    receive(entry.runtime_data)
    old = entry.runtime_data
    hass.config_entries.async_update_entry(
        entry, data=NETWORK | {"source_ip": "192.0.2.11"}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert udp_endpoint[0].closed
    assert old.pipeline.session_id != entry.runtime_data.pipeline.session_id
    assert ids == entity_ids(hass, entry)
    assert all(hass.states.get(id).state == STATE_UNAVAILABLE for id in ids.values())
    assert (
        dr.async_get(hass)
        .async_get_device_by_identifier((DOMAIN, entry.entry_id), entry.entry_id)
        .id
        == device.id
    )
    hass.config_entries.async_update_entry(entry, options={"profile": "observe_only"})
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert all(hass.states.get(id).state == STATE_UNAVAILABLE for id in ids.values())
    hass.config_entries.async_update_entry(entry, options={"profile": PROFILE.value})
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert ids == entity_ids(hass, entry)
    assert (
        len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)) == 8
    )


async def test_bind_error_is_retryable_and_leaves_no_timers(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=NETWORK)
    entry.add_to_hass(hass)
    with patch(
        "asyncio.BaseEventLoop.create_datagram_endpoint",
        side_effect=OSError("address in use"),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_invalid_persisted_configuration_fails_before_bind(hass, udp_endpoint):
    entry = MockConfigEntry(domain=DOMAIN, data=NETWORK, options={"profile": "guess"})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert not udp_endpoint


async def test_socket_failure_unavailable_reload_and_stop_cancels_recovery(
    hass, udp_endpoint, freezer
):
    entry = await setup_entry(hass)
    old = entry.runtime_data
    receive(old)
    old.listener.receiver.error_received(OSError("synthetic receive failure"))
    await hass.async_block_till_done()
    assert udp_endpoint[0].closed
    assert all(
        state.state == STATE_UNAVAILABLE for state in hass.states.async_all("sensor")
    )
    await advance(hass, freezer, 5)
    assert entry.runtime_data is not old
    assert entry.runtime_data.listener.receiver.running
    assert not entry.runtime_data.data
    current = entry.runtime_data
    current.listener.receiver.error_received(OSError("second failure"))
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    await advance(hass, freezer, 10)
    assert current._reload is None
    assert current._expiry is None
    assert current.listener._timer is None
    assert len(udp_endpoint) == 2


async def test_forwarding_failure_cleans_transport(hass, udp_endpoint):
    entry = MockConfigEntry(domain=DOMAIN, data=NETWORK)
    entry.add_to_hass(hass)
    with patch.object(
        hass.config_entries,
        "async_forward_entry_setups",
        side_effect=RuntimeError("platform forwarding failed"),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    assert udp_endpoint[0].closed
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_failed_unload_keeps_receiver_alive(hass, udp_endpoint):
    entry = await setup_entry(hass)
    with patch.object(
        hass.config_entries, "async_unload_platforms", return_value=False
    ):
        assert not await async_unload_entry(hass, entry)
    assert entry.runtime_data.listener.receiver.running
    assert not udp_endpoint[0].closed


async def test_cancel_setup_after_bind_cleans_everything(hass, udp_endpoint):
    entry = MockConfigEntry(domain=DOMAIN, data=NETWORK)
    entry.add_to_hass(hass)
    with patch.object(
        hass.config_entries,
        "async_forward_entry_setups",
        side_effect=asyncio.CancelledError,
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    assert udp_endpoint[0].closed


async def test_publish_guard_per_key_age_and_late_recovery(hass, udp_endpoint, freezer):
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    result = decode_frame(Frame(temperature_frame()), profile=PROFILE)
    observation = Observation(
        result,
        Origin.LIVE,
        coordinator.pipeline.session_id,
        ("192.0.2.10", 4001),
        datetime.now(UTC),
        coordinator.listener.receiver.elapsed,
        0.0,
        0,
    )
    for invalid in (
        replace(observation, origin=Origin.REPLAY),
        replace(observation, session_id="past session"),
        replace(observation, source=("192.0.2.11", 4001)),
        replace(observation, stream_time=1000),
        replace(
            observation, result=replace(result, profile=DecoderProfile.OBSERVE_ONLY)
        ),
    ):
        coordinator._observations([invalid])
        assert coordinator.data == {}
    coordinator._observations([observation])
    await advance(hass, freezer, 4)
    # Simulate a later decoder publishing just one known measurement. Freshness
    # must remain per key, independent of today's eight-value response layout.
    newer = replace(
        observation,
        stream_time=coordinator.listener.receiver.elapsed,
        record_index=1,
        result=replace(
            result, temperatures=(Temperature("outdoor_temperature", -1.0),)
        ),
    )
    coordinator._observations([newer])
    coordinator._observations([observation])  # old recovered response cannot overwrite
    await advance(hass, freezer, 1)
    assert set(coordinator.data) == {"outdoor_temperature"}
    assert coordinator.data["outdoor_temperature"].celsius == -1.0
    await advance(hass, freezer, 5)
    assert coordinator.data == {}
    # A previously unseen old frame recovered now must never appear as fresh.
    coordinator.latest.clear()
    coordinator._observations([observation])
    assert coordinator.data == {}
    await coordinator.async_shutdown()
    coordinator._observations([newer])
    assert coordinator.data == {}


async def test_silent_framing_recovery_uses_old_receipt_time(
    hass, udp_endpoint, freezer
):
    entry = await setup_entry(
        hass,
        options={
            "profile": PROFILE.value,
            "stale_timeout": 5,
            "partial_timeout": 10,
            "gap_timeout": 10,
        },
    )
    coordinator = entry.runtime_data
    receive(coordinator, b"\x00" * 10 + b"\xff" + temperature_frame())
    assert not coordinator.latest
    await advance(hass, freezer, 10)
    assert len(coordinator.latest) == 8
    assert coordinator.data == {}
    assert all(
        state.state == STATE_UNAVAILABLE for state in hass.states.async_all("sensor")
    )
    assert coordinator.diagnostics()["measurements"]["outdoor_temperature"][
        "age_seconds"
    ] == pytest.approx(10)


async def test_failure_after_entities_added_unloads_platform(hass, udp_endpoint):
    entry = MockConfigEntry(
        domain=DOMAIN, data=NETWORK, options={"profile": PROFILE.value}
    )
    entry.add_to_hass(hass)
    forward = hass.config_entries.async_forward_entry_setups

    async def failing_forward(*args):
        await forward(*args)
        await hass.async_block_till_done()
        assert len(hass.states.async_all("sensor")) == 8
        raise RuntimeError("failure after forwarding")

    with patch.object(
        hass.config_entries, "async_forward_entry_setups", failing_forward
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    assert udp_endpoint[0].closed
    # Registered entities can remain as unavailable placeholders; the actual
    # platform must have no live entities/listeners holding the old coordinator.
    from homeassistant.helpers.entity_platform import async_get_platforms

    assert all(not platform.entities for platform in async_get_platforms(hass, DOMAIN))


async def test_options_flow_actually_reloads_observation_into_sensors(
    hass, udp_endpoint
):
    entry = await setup_entry(hass, options={})
    old = entry.runtime_data
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "profile": PROFILE.value,
            "stale_timeout": 5,
            "partial_timeout": 1,
            "gap_timeout": 5,
        },
    )
    await hass.async_block_till_done()
    assert entry.runtime_data is not old
    assert udp_endpoint[0].closed
    assert len(hass.states.async_all("sensor")) == 8
    receive(entry.runtime_data)
    assert (
        hass.states.get(entity_ids(hass, entry)["outdoor_temperature"]).state == "-12.5"
    )
