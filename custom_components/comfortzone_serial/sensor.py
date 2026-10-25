"""Temperature entities for explicitly selected layouts, all enabled by default."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME
from .coordinator import ComfortZoneConfigEntry, ComfortZoneCoordinator
from .telemetry.decoder import (
    EX35_TEMPERATURE_KEYS,
    temperature_keys,
)

PARALLEL_UPDATES = 0
SENSORS = tuple(
    SensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    )
    for key in EX35_TEMPERATURE_KEYS
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ComfortZoneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    keys = temperature_keys(entry.runtime_data.decoder.profile)
    if keys:
        async_add_entities(
            ComfortZoneTemperature(entry.runtime_data, description)
            for description in SENSORS
            if description.key in keys
        )


class ComfortZoneTemperature(CoordinatorEntity[ComfortZoneCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: ComfortZoneCoordinator, description: SensorEntityDescription
    ) -> None:
        super().__init__(coordinator, context=description.key)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name=NAME,
            manufacturer="ComfortZone",
        )

    @property
    def available(self) -> bool:
        return (
            super().available and self.entity_description.key in self.coordinator.data
        )

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.data.get(self.entity_description.key)
        return value.celsius if value is not None else None
