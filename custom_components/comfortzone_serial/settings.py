"""Validate persisted settings as well as form input, without network probes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    CONF_BIND_HOST,
    CONF_BIND_PORT,
    CONF_DESTINATION_PORT,
    CONF_GAP_TIMEOUT,
    CONF_PARTIAL_TIMEOUT,
    CONF_POLL_INTERVAL,
    CONF_POLLING_ENABLED,
    CONF_PROFILE,
    CONF_PUMP_ADDRESS,
    CONF_READ_QUERIES,
    CONF_REQUEST_DELAY,
    CONF_SOURCE_IP,
    CONF_SOURCE_PORT,
    CONF_STALE_TIMEOUT,
    NETWORK_DEFAULTS,
    OPTION_DEFAULTS,
)
from .telemetry.decoder import DecoderProfile
from .telemetry.polling import RESPONSE_TIMEOUT, PollingSettings
from .telemetry.queries import ReadDefinition, individual_reads
from .telemetry.stream import finite_seconds
from .telemetry.udp import NetworkSettings


def network_settings(data: Mapping[str, Any]) -> NetworkSettings:
    """Zero is the UI's explicit 'any source port' value."""
    values = NETWORK_DEFAULTS | dict(data)
    source_port = values[CONF_SOURCE_PORT]
    if type(source_port) is not int:
        raise ValueError("Source port must be an integer")
    return NetworkSettings(
        source_ip=values[CONF_SOURCE_IP],
        bind_host=values[CONF_BIND_HOST],
        bind_port=values[CONF_BIND_PORT],
        source_port=None if source_port == 0 else source_port,
    )


@dataclass(frozen=True, slots=True)
class DecoderSettings:
    profile: DecoderProfile
    stale_timeout: float
    partial_timeout: float
    gap_timeout: float
    polling: PollingSettings | None
    reads: tuple[ReadDefinition, ...]
    address: str

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> DecoderSettings:
        values = OPTION_DEFAULTS | dict(options)
        stale = finite_seconds(values[CONF_STALE_TIMEOUT])
        partial = finite_seconds(values[CONF_PARTIAL_TIMEOUT])
        gap = finite_seconds(values[CONF_GAP_TIMEOUT])
        if not 5 <= stale <= 86400:
            raise ValueError("Stale timeout must be between 5 and 86400 seconds")
        if not 0.01 <= partial <= 60:
            raise ValueError("Partial timeout must be between 0.01 and 60 seconds")
        if not partial <= gap <= 3600:
            raise ValueError("Gap timeout must be between partial timeout and 3600")
        profile = DecoderProfile(values[CONF_PROFILE])
        enabled = values[CONF_POLLING_ENABLED]
        if type(enabled) is not bool:
            raise ValueError("Polling enabled must be a boolean")
        names = values[CONF_READ_QUERIES]
        if not isinstance(names, (list, tuple)):
            raise ValueError("Read selection must be a list")
        reads = individual_reads(tuple(names))
        polling = PollingSettings(
            interval=values[CONF_POLL_INTERVAL],
            destination_port=values[CONF_DESTINATION_PORT],
            address=values[CONF_PUMP_ADDRESS],
            read_names=tuple(read.name for read in reads),
            cycle=True,
            request_delay=values[CONF_REQUEST_DELAY],
        )
        if enabled:
            if profile is not DecoderProfile.EX35_0B15:
                raise ValueError("Polling requires the EX35 0b15 profile")
            if stale <= max(polling.interval, len(reads) * polling.request_delay):
                raise ValueError("Freshness limit must exceed the cycle and its pauses")
            if partial >= RESPONSE_TIMEOUT:
                raise ValueError("Incomplete frame timeout must be below 10 seconds")
        return cls(
            profile,
            stale,
            partial,
            gap,
            polling if enabled else None,
            reads,
            polling.address,
        )
