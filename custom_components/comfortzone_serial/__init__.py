"""Read-only ComfortZone Serial; offline tooling needs no HA installation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import ComfortZoneConfigEntry


async def async_migrate_entry(
    hass: HomeAssistant, entry: ComfortZoneConfigEntry
) -> bool:
    """Preserve existing acquisition choices and migrate sensor defaults once."""
    from homeassistant.helpers import entity_registry as er

    from .const import DOMAIN
    from .telemetry.decoder import EX35_TEMPERATURE_KEYS

    if entry.version != 1:
        return False
    if entry.minor_version < 2:
        # Respect explicit entity disables and the user's global preference to
        # disable new entities. All temperature keys receive identical treatment.
        if not entry.pref_disable_new_entities:
            registry = er.async_get(hass)
            for key in EX35_TEMPERATURE_KEYS:
                entity_id = registry.async_get_entity_id(
                    "sensor", DOMAIN, f"{entry.entry_id}_{key}"
                )
                if entity_id is None:
                    continue
                entity = registry.async_get(entity_id)
                if (
                    entity.config_entry_id == entry.entry_id
                    and entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION
                ):
                    registry.async_update_entity(entity_id, disabled_by=None)
        hass.config_entries.async_update_entry(entry, minor_version=2)
    if entry.minor_version < 3:
        from .const import (
            CONF_POLLING_ENABLED,
            CONF_PROFILE,
            CONF_SOURCE_PORT,
            OPTION_DEFAULTS,
        )

        # Former defaults were observation-only, passive, any source port.
        # New default reads apply to EX35 entries; explicit choices remain intact.
        options = (
            OPTION_DEFAULTS
            | {
                CONF_PROFILE: "observe_only",
                CONF_POLLING_ENABLED: False,
            }
            | entry.options
        )
        data = {CONF_SOURCE_PORT: 0} | entry.data
        hass.config_entries.async_update_entry(
            entry,
            options=options,
            data=data,
            minor_version=3,
        )
    return True


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
