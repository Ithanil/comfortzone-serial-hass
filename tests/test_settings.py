"""Persisted individual-read settings are validated before allocating resources."""

import pytest

from custom_components.comfortzone_serial.const import DEFAULT_READ_QUERIES
from custom_components.comfortzone_serial.settings import (
    DecoderSettings,
    network_settings,
)
from custom_components.comfortzone_serial.telemetry.decoder import DecoderProfile
from custom_components.comfortzone_serial.telemetry.polling import PollingSettings
from custom_components.comfortzone_serial.telemetry.queries import individual_reads


def test_default_individual_reads_and_cycle_settings():
    settings = DecoderSettings.from_options({})
    assert settings.profile is DecoderProfile.EX35_0B15
    assert settings.polling.cycle
    assert settings.polling.interval == 60
    assert settings.polling.request_delay == 0.25
    assert settings.stale_timeout == 120
    assert settings.partial_timeout == 1 and settings.gap_timeout == 5
    assert tuple(read.name for read in settings.reads) == DEFAULT_READ_QUERIES
    assert settings.polling.reads == settings.reads
    assert network_settings({"source_ip": "192.0.2.1"}).source_port == 4001
    assert (
        network_settings({"source_ip": "192.0.2.1", "source_port": 0}).source_port
        is None
    )


@pytest.mark.parametrize(
    "names", [[], (), "power", ["operation"], [None], [1], ["write"]]
)
def test_invalid_individual_names_fail_without_transport(names):
    with pytest.raises(ValueError):
        DecoderSettings.from_options({"read_queries": names})


def test_individual_reads_preserve_order_without_expanding_groups():
    names = ("fan_settings", "temperature", "fan_settings", "compressor")
    settings = PollingSettings(cycle=True, read_names=names)
    assert [read.name for read in settings.reads] == [
        "fan_settings",
        "temperature",
        "compressor",
    ]
    assert settings.reads == individual_reads(names)
    with pytest.raises(ValueError, match="not both"):
        PollingSettings(queries=("power",), read_names=names)
    # CLI query groups and legacy fixed-rate consumers retain their behavior.
    assert PollingSettings().reads[0].name == "temperature"
    assert not PollingSettings().cycle
    assert len(PollingSettings(queries=("operation",)).reads) == 3


@pytest.mark.parametrize(
    "options",
    [
        {"request_delay": float("nan")},
        {"request_delay": True},
        {"request_delay": -1},
        {"poll_interval": 0},
        {"poll_interval": float("inf")},
        {"poll_interval": 120},
        {"request_delay": 24},
        {"partial_timeout": 10, "gap_timeout": 10},
        {"profile": "observe_only"},
        {"polling_enabled": "yes"},
    ],
)
def test_invalid_persisted_options(options):
    with pytest.raises(ValueError):
        DecoderSettings.from_options(options)


def test_fractional_cycles_and_explicit_passive_mode():
    settings = DecoderSettings.from_options({"poll_interval": 0.1, "request_delay": 0})
    assert settings.polling.interval == 0.1
    assert DecoderSettings.from_options({"polling_enabled": False}).polling is None


def test_long_cycles_can_have_a_longer_freshness_limit():
    settings = DecoderSettings.from_options(
        {"poll_interval": 3600, "stale_timeout": 7200}
    )
    assert settings.polling.interval < settings.stale_timeout
    with pytest.raises(ValueError):
        DecoderSettings.from_options({"stale_timeout": 86401})
