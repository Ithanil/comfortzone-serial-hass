"""Individual HA reads, sensor metadata and shared-link lifecycle with fake UDP."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed_exact,
)

from custom_components.comfortzone_serial.const import (
    DEFAULT_READ_QUERIES,
    DOMAIN,
    OPTION_DEFAULTS,
)
from custom_components.comfortzone_serial.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.comfortzone_serial.telemetry.framing import Frame
from custom_components.comfortzone_serial.telemetry.queries import READS_BY_NAME
from tests.ha.test_config_flow import NETWORK
from tests.ha.test_runtime import receive
from tests.test_queries import captured_frames, corrected

pytestmark = pytest.mark.asyncio


async def advance(hass, freezer, seconds):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed_exact(hass, datetime.now(UTC))
    await hass.async_block_till_done()


async def entry_for(hass, **options):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="ComfortZone Serial",
        version=1,
        minor_version=3,
        data=NETWORK | {"source_port": 4001},
        options=OPTION_DEFAULTS | options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def ids_for(hass, entry):
    return {
        e.unique_id.removeprefix(entry.entry_id + "_"): e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }


def response(name):
    return captured_frames()[READS_BY_NAME[name].register].raw


async def test_default_cycle_updates_all_five_reads_and_preserves_timing(
    hass, polling_endpoint, freezer
):
    entry = await entry_for(hass)
    coordinator = entry.runtime_data
    ids = ids_for(hass, entry)
    transport = polling_endpoint[0]
    assert len(ids) == 27
    clock_id = ids.pop("pump_clock")
    assert er.async_get(hass).async_get(clock_id).disabled_by is (
        er.RegistryEntryDisabler.INTEGRATION
    )
    assert hass.states.get(clock_id) is None
    assert len(hass.states.async_all("sensor")) == 26
    assert all(hass.states.get(id).state == STATE_UNAVAILABLE for id in ids.values())
    for index, name in enumerate(DEFAULT_READ_QUERIES):
        assert len(transport.sent) == index + 1
        assert Frame(transport.sent[-1][0]).register == READS_BY_NAME[name].register
        raw = response(name)
        receive(coordinator, raw[:24])
        assert coordinator.listener._sent_at is not None
        receive(coordinator, raw[24:])
        assert coordinator.listener._sent_at is None
        await advance(hass, freezer, 0.24)
        assert len(transport.sent) == index + 1
        await advance(hass, freezer, 0.01)
    expected = {
        "outdoor_temperature": "10.3",
        "compressor_heat_output": "1340",
        "compressor_electrical_input": "400",
        "compressor_energy": "2644.08",
        "compressor_runtime": "98503",
        "heating_curve": "3.0",
        "hot_water_setpoint": "50.0",
    }
    for key, value in expected.items():
        state = hass.states.get(ids[key])
        assert state.state == value
        assert "raw_hex" not in state.attributes
    assert all(hass.states.get(id).state != STATE_UNAVAILABLE for id in ids.values())
    power = hass.states.get(ids["compressor_electrical_input"])
    assert power.attributes["device_class"] == "power"
    assert power.attributes["state_class"] == "measurement"
    assert power.attributes["unit_of_measurement"] == "W"
    energy = hass.states.get(ids["compressor_energy"])
    assert energy.attributes["device_class"] == "energy"
    assert energy.attributes["unit_of_measurement"] == "kWh"
    assert "state_class" not in energy.attributes
    assert "state_class" not in hass.states.get(ids["hot_water_setpoint"]).attributes
    assert coordinator.data["pump_clock"].value == "2026-10-24T21:27:54"
    assert hass.states.get(clock_id) is None
    assert hass.states.get(ids["hot_water_hysteresis"]).attributes["device_class"] == (
        "temperature_delta"
    )
    await advance(hass, freezer, 58.74)
    assert len(transport.sent) == 5
    await advance(hass, freezer, 0.01)
    assert len(transport.sent) == 6
    assert (
        Frame(transport.sent[-1][0]).register == READS_BY_NAME["temperature"].register
    )
    timer = coordinator.listener._response_timer
    assert await hass.config_entries.async_unload(entry.entry_id)
    await advance(hass, freezer, 60)
    assert timer.cancelled() and transport.closed and len(transport.sent) == 6


async def test_optional_reads_and_unknown_response_stay_out_of_attributes(
    hass, polling_endpoint, freezer
):
    entry = await entry_for(hass, read_queries=list(READS_BY_NAME), request_delay=0)
    coordinator = entry.runtime_data
    ids = ids_for(hass, entry)
    assert len(ids) == 43
    registry = er.async_get(hass)
    disabled = {
        key
        for key, id in ids.items()
        if registry.async_get(id).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    }
    assert disabled == {"pump_clock", "compressor_response"}
    assert len(hass.states.async_all("sensor")) == 41
    for name in READS_BY_NAME:
        receive(coordinator, response(name))
        await advance(hass, freezer, 0.001)
    assert len(polling_endpoint[0].sent) == 9
    for key, value in {
        "te1_calibration": "1.3",
        "ui_software_version": "2.30.0",
        "ui_hardware_revision_code": "10",
        "reduced_fan_setting": "-30.0",
    }.items():
        assert hass.states.get(ids[key]).state == value
    assert "compressor_frequency" not in ids
    assert "alarm_flags" not in ids
    assert "operating_mode" not in ids
    assert "compressor_state" not in ids
    assert hass.states.get(ids["te1_calibration"]).attributes["device_class"] == (
        "temperature_delta"
    )
    diagnostic = await async_get_config_entry_diagnostics(hass, entry)
    assert len(diagnostic["read_replies"]) == 9
    compressor = diagnostic["read_replies"]["compressor"]
    assert compressor["raw_hex"] == response("compressor").hex()
    assert compressor["fields"][0]["status"] == "unknown"
    assert (
        compressor["unknown_regions"][0]["raw_hex"]
        == Frame(response("compressor")).payload.hex()
    )
    assert "192.0.2.10" not in json.dumps(diagnostic)
    for key, id in ids.items():
        if key in disabled:
            assert hass.states.get(id) is None
        else:
            assert "raw_hex" not in hass.states.get(id).attributes


async def test_independent_freshness_unknown_clock_and_unselected_read(
    hass, udp_endpoint, freezer
):
    entry = await entry_for(
        hass,
        polling_enabled=False,
        stale_timeout=5,
        read_queries=["temperature", "power", "compressor"],
    )
    ids = ids_for(hass, entry)
    registry = er.async_get(hass)
    for key in ("pump_clock", "compressor_response"):
        assert registry.async_get(ids[key]).disabled_by is (
            er.RegistryEntryDisabler.INTEGRATION
        )
        registry.async_update_entity(ids[key], disabled_by=None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert ids_for(hass, entry) == ids
    assert all(
        registry.async_get(ids[key]).disabled_by is None
        for key in ("pump_clock", "compressor_response")
    )
    coordinator = entry.runtime_data
    receive(coordinator, response("temperature"))
    assert hass.states.get(ids["pump_clock"]).state == "2026-10-24T21:27:54"
    assert "device_class" not in hass.states.get(ids["pump_clock"]).attributes
    original = coordinator.pipeline.recent_frames[-1]
    receive(coordinator, response("compressor"))
    assert hass.states.get(ids["compressor_response"]).state == "undecoded"
    receive(coordinator, response("fan_settings"))
    assert "fan_settings" not in coordinator.read_replies
    assert "reduced_fan_setting" not in coordinator.data
    await advance(hass, freezer, 4)
    raw = bytearray(response("temperature"))
    raw[25] = 13  # Invalid clock month, while temperature fields remain valid.
    raw[76:78] = bytes.fromhex("22fc")
    receive(coordinator, corrected(raw).raw)
    coordinator._observations([original])  # An older frame cannot undo invalidation.
    assert hass.states.get(ids["outdoor_temperature"]).state == STATE_UNAVAILABLE
    assert hass.states.get(ids["pump_clock"]).state == STATE_UNKNOWN
    assert hass.states.get(ids["indoor_temperature"]).state == "22.2"
    receive(coordinator, response("power"))
    await advance(hass, freezer, 1.1)
    assert hass.states.get(ids["compressor_response"]).state == STATE_UNAVAILABLE
    assert hass.states.get(ids["compressor_heat_output"]).state == "1340"
    await advance(hass, freezer, 4)
    assert all(hass.states.get(id).state == STATE_UNAVAILABLE for id in ids.values())


async def test_shared_traffic_survives_timeout_and_next_send(
    hass, polling_endpoint, freezer
):
    entry = await entry_for(hass, read_queries=["power", "temperature"])
    coordinator = entry.runtime_data
    ids = ids_for(hass, entry)
    listener = coordinator.listener
    # A temperature reply from another poller straddles our power timeout and
    # next temperature request. It must survive both without completing ours.
    await advance(hass, freezer, 9.8)
    raw = response("temperature")
    receive(coordinator, raw[:104])
    await advance(hass, freezer, 0.2)
    assert listener.poll_stats.timeouts == 1
    await advance(hass, freezer, 0.25)
    assert len(polling_endpoint[0].sent) == 2
    receive(coordinator, raw[104:])
    assert hass.states.get(ids["outdoor_temperature"]).state == "10.3"
    assert listener.poll_stats.replies_received == 0
    assert listener._sent_at is not None
    # An unrelated complete power response updates power but not the pending read.
    receive(coordinator, response("power"))
    assert hass.states.get(ids["compressor_heat_output"]).state == "1340"
    assert listener._sent_at is not None
    receive(coordinator, raw)
    assert listener.poll_stats.replies_received == 1
    assert listener._sent_at is None


async def test_ex35_receive_guards_reject_wrong_envelopes_and_replay(
    hass, udp_endpoint
):
    entry = await entry_for(hass, polling_enabled=False, read_queries=["power"])
    coordinator = entry.runtime_data
    raw = response("power")
    for endpoint in (("192.0.2.11", 4001), ("192.0.2.10", 4002)):
        coordinator.listener.receiver.datagram_received(raw, endpoint)
    for index in (0, 4, 5, 6, 11, 17):
        bad = bytearray(raw)
        bad[index] ^= 1
        receive(coordinator, corrected(bad).raw)
    receive(coordinator, corrected(raw[:-2] + raw[-1:]).raw)
    bad = bytearray(raw)
    bad[22] ^= 1  # Broken full-frame CRC.
    receive(coordinator, bytes(bad))
    assert not coordinator.data and not coordinator.read_replies
    receive(coordinator, raw)
    original = coordinator.pipeline.recent_frames[-1]
    coordinator.latest.clear()
    coordinator.read_replies.clear()
    from custom_components.comfortzone_serial.telemetry.stream import Origin

    for change in (
        {"origin": Origin.REPLAY},
        {"session_id": "old"},
        {"stream_time": 1000},
        {"source": ("192.0.2.12", 4001)},
    ):
        coordinator._observations([replace(original, **change)])
        assert not coordinator.latest and not coordinator.read_replies


async def test_selection_reload_preserves_ids_and_user_disable(hass, polling_endpoint):
    entry = await entry_for(hass)
    registry = er.async_get(hass)
    ids = ids_for(hass, entry)
    disabled = ids["indoor_temperature"]
    registry.async_update_entity(disabled, disabled_by=er.RegistryEntryDisabler.USER)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        dict(entry.options)
        | {
            "read_queries": ["power", "calibration", "compressor"],
            "poll_interval": 2,
            "request_delay": 0.1,
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert polling_endpoint[0].closed
    assert entry.runtime_data.decoder.polling.reads[0].name == "power"
    receive(entry.runtime_data, response("temperature"))
    assert "outdoor_temperature" not in entry.runtime_data.data
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        flow["flow_id"],
        dict(entry.options) | {"read_queries": list(DEFAULT_READ_QUERIES)},
    )
    await hass.async_block_till_done()
    assert all(ids_for(hass, entry)[key] == id for key, id in ids.items())
    assert registry.async_get(disabled).disabled_by is er.RegistryEntryDisabler.USER


@pytest.mark.parametrize("enabled", [False, True])
async def test_migration_preserves_acquisition_and_enables_default_reads(
    hass, polling_endpoint, enabled
):
    options = {
        "profile": "ex35_0b15_temperatures_v1",
        "polling_enabled": enabled,
        "poll_interval": 42,
        "stale_timeout": 180,
        "destination_port": 4002,
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        minor_version=2,
        data={"source_ip": NETWORK["source_ip"]},
        options=options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.options == OPTION_DEFAULTS | options
    assert entry.data["source_port"] == 0
    assert entry.minor_version == 3
    assert (
        entry.runtime_data.decoder.polling is not None
        if enabled
        else (entry.runtime_data.decoder.polling is None)
    )
    assert len(polling_endpoint[0].sent) == int(enabled)
    if enabled:
        assert polling_endpoint[0].sent[0][1][1] == 4002


async def test_new_setup_can_disable_polling_and_uses_port_4001(hass, udp_endpoint):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"source_ip": NETWORK["source_ip"], "polling_enabled": False},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.data["source_port"] == 4001
    assert entry.runtime_data.decoder.polling is None
    assert len(ids_for(hass, entry)) == 27


@pytest.mark.parametrize(
    "changes",
    [
        {"read_queries": []},
        {"read_queries": ["operation"]},
        {"read_queries": ["write"]},
        {"poll_interval": 0},
        {"poll_interval": float("inf")},
        {"request_delay": -1},
        {"request_delay": 30},
        {"partial_timeout": 10, "gap_timeout": 10},
    ],
)
async def test_invalid_individual_read_options(hass, changes):
    entry = MockConfigEntry(domain=DOMAIN, version=1, minor_version=3, data=NETWORK)
    entry.add_to_hass(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    # Schema-level invalid selectors/ranges can be rejected before the step.
    from homeassistant.data_entry_flow import InvalidData

    try:
        result = await hass.config_entries.options.async_configure(
            flow["flow_id"],
            OPTION_DEFAULTS | changes,
        )
    except InvalidData:
        return
    assert result["errors"] == {"base": "invalid_options"}


async def test_temperature_difference_units_convert_without_absolute_offset(
    hass, udp_endpoint
):
    from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

    hass.config.units = US_CUSTOMARY_SYSTEM
    entry = await entry_for(
        hass,
        polling_enabled=False,
        read_queries=["temperature", "calibration", "hot_water_settings"],
    )
    ids = ids_for(hass, entry)
    registry = er.async_get(hass)
    for key in ("outdoor_temperature", "te1_calibration", "hot_water_hysteresis"):
        registry.async_update_entity_options(
            ids[key], "sensor", {"unit_of_measurement": "°F"}
        )
    await hass.async_block_till_done()
    receive(entry.runtime_data, response("temperature"))
    receive(entry.runtime_data, response("calibration"))
    receive(entry.runtime_data, response("hot_water_settings"))
    for key, expected in (
        ("outdoor_temperature", 50.54),
        ("te1_calibration", 2.34),
        ("hot_water_hysteresis", 9.0),
    ):
        state = hass.states.get(ids[key])
        assert state.attributes["unit_of_measurement"] == "°F"
        assert float(state.state) == pytest.approx(expected)
