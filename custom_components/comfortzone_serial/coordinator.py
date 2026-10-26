"""UDP acquisition, optional read polling and per-measurement freshness."""

import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .settings import DecoderSettings, network_settings
from .telemetry.decoder import (
    DECODED_REASONS,
    DecoderProfile,
    temperature_keys,
)
from .telemetry.polling import pump_address
from .telemetry.readings import decode_readings, reading_keys
from .telemetry.stream import Observation, Origin, TelemetryPipeline
from .telemetry.udp import TelemetryListener

_LOGGER = logging.getLogger(__name__)
RELOAD_DELAY = 5.0


@dataclass(frozen=True, slots=True)
class Measurement:
    value: int | float | str | None
    status: str
    unit: str | None
    received_at: datetime
    stream_time: float
    record_index: int


type ComfortZoneConfigEntry = ConfigEntry[ComfortZoneCoordinator]


class ComfortZoneCoordinator(DataUpdateCoordinator[dict[str, Measurement]]):
    """Own one live session. Replays and past sessions cannot update entities."""

    config_entry: ComfortZoneConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ComfortZoneConfigEntry) -> None:
        # Validate before allocating resources or registering unload callbacks.
        self.settings = network_settings(entry.data)
        self.decoder = DecoderSettings.from_options(entry.options)
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN, always_update=False
        )
        self.pipeline = TelemetryPipeline(
            session_id=uuid4().hex,
            origin=Origin.LIVE,
            profile=self.decoder.profile,
            partial_timeout=self.decoder.partial_timeout,
            gap_timeout=self.decoder.gap_timeout,
        )
        self.listener = TelemetryListener(
            self.settings,
            self.pipeline,
            self._observations,
            self._receiver_error,
            polling=self.decoder.polling,
            receive_all=True,
        )
        self.data = {}
        self.latest: dict[str, Measurement] = {}
        self.read_replies: dict[str, dict] = {}
        self._reads = {read.register: read for read in self.decoder.reads}
        self._expiry: asyncio.TimerHandle | None = None
        self._reload: asyncio.TimerHandle | None = None
        self._remove_stop = None
        self._started = False
        self._closed = False
        self.receiver_error: str | None = None

    async def async_start(self) -> None:
        """Bind and start configured acquisition; silence is not a setup failure."""
        self._remove_stop = self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, self._stop
        )
        try:
            await self.listener.start()
            if self._closed or not self.listener.receiver.running:
                raise OSError("UDP receiver closed during setup")
            self._started = True
        except OSError as error:
            await self.async_shutdown()
            raise ConfigEntryNotReady(
                "Unable to bind the local UDP receiver"
            ) from error
        except BaseException:
            await self.async_shutdown()
            raise

    async def _stop(self, _: Event) -> None:
        await self.async_shutdown()

    async def async_shutdown(self) -> None:
        """Idempotent cleanup also covers failed setup and HA stop."""
        self._closed = True
        self._started = False
        for timer in (self._expiry, self._reload):
            if timer is not None:
                timer.cancel()
        self._expiry = self._reload = None
        if self._remove_stop is not None:
            self._remove_stop()
            self._remove_stop = None
        self.listener.close()
        self.data = {}
        self.async_update_listeners()
        await self.listener.wait_closed()
        await super().async_shutdown()

    @callback
    def _observations(self, observations: list[Observation]) -> None:
        if self._closed or not self.listener.receiver.running:
            return
        now = self.listener.receiver.elapsed
        changed = False
        for observation in observations:
            if (
                observation.origin is not Origin.LIVE
                or observation.session_id != self.pipeline.session_id
                or observation.result.profile is not self.decoder.profile
                or not self.settings.accepts(observation.source)
                or not 0 <= observation.stream_time <= now
            ):
                continue
            frame = observation.result.frame
            if self.decoder.profile is DecoderProfile.EX35_0B15:
                read = self._reads.get(frame.register)
                if (
                    read is None
                    or frame.raw[6:10] != pump_address(self.decoder.address)
                    or len(frame.payload) != read.payload_length
                ):
                    continue
                decoded = decode_readings(frame)
                if decoded.reason not in ("decoded", "unmapped_payload"):
                    continue
                previous_reply = self.read_replies.get(read.name)
                order = (observation.stream_time, observation.record_index)
                if previous_reply and order <= previous_reply["order"]:
                    continue
                self.read_replies[read.name] = {
                    "order": order,
                    "received_at": observation.received_at.isoformat(),
                    "raw_hex": frame.raw.hex(),
                    "decode_reason": decoded.reason,
                    **decoded.as_dict(),
                }
                keys = reading_keys(read)
                values = [
                    (field.key, field.value, field.status, field.unit)
                    for field in decoded.fields
                    if field.key in keys
                ]
                if read.name == "compressor":
                    # Report reception without inventing a frequency or state.
                    values.append(("compressor_response", "undecoded", "decoded", None))
            elif observation.result.reason in DECODED_REASONS:
                values = [
                    (
                        t.key,
                        t.celsius,
                        "unavailable" if t.celsius is None else "decoded",
                        "°C",
                    )
                    for t in observation.result.temperatures
                    if t.key in temperature_keys(self.decoder.profile)
                ]
            else:
                continue
            for key, value, status, unit in values:
                previous = self.latest.get(key)
                if previous is not None and (
                    observation.stream_time,
                    observation.record_index,
                ) <= (previous.stream_time, previous.record_index):
                    continue
                self.latest[key] = Measurement(
                    value,
                    status,
                    unit,
                    observation.received_at,
                    observation.stream_time,
                    observation.record_index,
                )
                changed = True
        if changed:
            self._publish_fresh()

    @callback
    def _publish_fresh(self) -> None:
        """Expire on the original byte receipt time, even after delayed framing."""
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None
        if self._closed or not self.listener.receiver.running:
            return
        now = self.listener.receiver.elapsed
        fresh = {
            key: value
            for key, value in self.latest.items()
            if 0 <= now - value.stream_time < self.decoder.stale_timeout
        }
        self.async_set_updated_data(fresh)
        if fresh:
            deadline = min(value.stream_time for value in fresh.values())
            delay = deadline + self.decoder.stale_timeout - now
            self._expiry = self.hass.loop.call_later(
                max(0.001, delay), self._publish_fresh
            )

    @callback
    def _receiver_error(self, error: Exception) -> None:
        if self._closed:
            return
        # Do not log raw frames, addresses or unbounded exception text.
        self.receiver_error = type(error).__name__
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None
        self.data = {}
        self.async_set_update_error(UpdateFailed("Local UDP receiver stopped"))
        if self._started and self._reload is None and not self.hass.is_stopping:
            self._reload = self.hass.loop.call_later(RELOAD_DELAY, self._request_reload)

    @callback
    def _request_reload(self) -> None:
        self._reload = None
        if not self._closed and not self.hass.is_stopping:
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)

    async def async_request_refresh(self) -> None:
        """Reevaluate age; the single polling timer owns all serial requests."""
        self._publish_fresh()

    def diagnostics(self) -> dict:
        """Bounded evidence, separate from recorded sensor attributes."""
        now = self.listener.receiver.elapsed
        decoder_settings = asdict(self.decoder)
        decoder_settings["reads"] = [read.name for read in self.decoder.reads]
        return {
            "network_settings": asdict(self.settings),
            "receiver_running": self.listener.receiver.running,
            "receiver_error_type": self.receiver_error,
            "receiver_stats": asdict(self.listener.receiver.stats),
            "decoder_settings": decoder_settings,
            "read_replies": {
                name: {
                    **{k: v for k, v in reply.items() if k != "order"},
                    "age_seconds": max(0, now - reply["order"][0]),
                }
                for name, reply in self.read_replies.items()
            },
            "polling_stats": asdict(self.listener.poll_stats),
            "measurements": {
                key: {
                    "value": value.value,
                    "status": value.status,
                    "unit": value.unit,
                    "received_at": value.received_at.isoformat(),
                    "age_seconds": max(0, now - value.stream_time),
                    "record_index": value.record_index,
                    "available": (
                        key in self.data
                        and not self._closed
                        and value.status != "unavailable"
                    ),
                }
                for key, value in self.latest.items()
            },
            "telemetry": self.pipeline.diagnostics(),
        }
