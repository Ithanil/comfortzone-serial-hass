"""Download bounded evidence without exposing configured network identifiers."""

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import ComfortZoneConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ComfortZoneConfigEntry
) -> dict:
    # Opaque bytes may contain identifiers unknown to this decoder; review before
    # sharing. Keep them exact for diagnosis, outside recorded entity attributes.
    return async_redact_data(
        entry.runtime_data.diagnostics(),
        {"source", "source_ip", "bind_host", "session_id"},
    )
