"""Read-only ComfortZone Serial; offline tooling needs no HA installation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import ComfortZoneConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: ComfortZoneConfigEntry) -> bool:
    # Lazy imports keep capture/replay and protocol tests independent of HA.
    from homeassistant.const import Platform
    from homeassistant.exceptions import ConfigEntryError

    from .coordinator import ComfortZoneCoordinator

    try:
        coordinator = ComfortZoneCoordinator(hass, entry)
    except (ValueError, KeyError, TypeError) as error:
        raise ConfigEntryError("Invalid local receiver configuration") from error
    entry.runtime_data = coordinator
    try:
        await coordinator.async_start()
    except BaseException:
        await coordinator.async_shutdown()
        raise
    try:
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    except BaseException:
        await coordinator.async_shutdown()
        # Forwarding can fail after entities have already been added.
        await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR])
        raise
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ComfortZoneConfigEntry
) -> bool:
    from homeassistant.const import Platform

    if not await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR]):
        return False
    await entry.runtime_data.async_shutdown()
    return True
