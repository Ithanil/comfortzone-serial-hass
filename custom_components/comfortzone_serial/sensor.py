"""Read-only entities for selected reads; raw evidence stays in diagnostics."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME
from .coordinator import ComfortZoneConfigEntry, ComfortZoneCoordinator
from .telemetry.decoder import (
    EX35_TEMPERATURE_KEYS,
    DecoderProfile,
    temperature_keys,
)
from .telemetry.readings import reading_keys

PARALLEL_UPDATES = 0


def _description(key: str, **kwargs) -> SensorEntityDescription:
    return SensorEntityDescription(key=key, translation_key=key, **kwargs)


SENSORS = (
    *(
        _description(
            key,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            suggested_display_precision=1,
        )
        for key in EX35_TEMPERATURE_KEYS
    ),
    *(
        _description(
            key,
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfPower.WATT,
            suggested_display_precision=0,
        )
        for key in (
            "compressor_heat_output",
            "auxiliary_heat_output",
            "total_heat_output_1",
            "total_heat_output_2",
            "compressor_electrical_input",
        )
    ),
    *(
        _description(
            key,
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            suggested_display_precision=2,
            # Reset/rollover and energy accounting semantics are not established.
            # Keep the raw counter/history without inventing accumulated statistics.
        )
        for key in ("compressor_energy", "auxiliary_energy", "hot_water_energy")
    ),
    *(
        _description(
            key,
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            suggested_display_precision=0,
        )
        for key in ("compressor_runtime", "total_runtime", "extra_hot_water_duration")
    ),
    _description("heating_curve", suggested_display_precision=1),
    *(
        _description(
            key,
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            suggested_display_precision=1,
        )
        for key in (
            "calculated_heating_setting",
            "hot_water_setpoint",
            "extra_hot_water_setpoint",
        )
    ),
    _description(
        "hot_water_hysteresis",
        device_class=SensorDeviceClass.TEMPERATURE_DELTA,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    *(
        _description(
            f"te{i}_calibration",
            device_class=SensorDeviceClass.TEMPERATURE_DELTA,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            suggested_display_precision=1,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        for i in range(10)
    ),
    *(
        _description(
            key,
            native_unit_of_measurement=PERCENTAGE,
            suggested_display_precision=1,
        )
        for key in ("normal_fan_setting", "reduced_fan_setting", "high_fan_setting")
    ),
    _description(
        "pump_clock",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    *(
        _description(key, entity_category=EntityCategory.DIAGNOSTIC)
        for key in (
            "pump_weekday",
            "ui_software_version",
            "ui_hardware_revision_code",
        )
    ),
    _description(
        "compressor_response",
        device_class=SensorDeviceClass.ENUM,
        options=["undecoded"],
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ComfortZoneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    decoder = entry.runtime_data.decoder
    if decoder.profile is DecoderProfile.EX35_0B15:
        keys = set().union(*(reading_keys(read) for read in decoder.reads))
        if any(read.name == "compressor" for read in decoder.reads):
            keys.add("compressor_response")
    else:
        keys = temperature_keys(decoder.profile)
    async_add_entities(
        ComfortZoneSensor(entry.runtime_data, description)
        for description in SENSORS
        if description.key in keys
    )


class ComfortZoneSensor(CoordinatorEntity[ComfortZoneCoordinator], SensorEntity):
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
        value = self.coordinator.data.get(self.entity_description.key)
        return super().available and value is not None and value.status != "unavailable"

    @property
    def native_value(self) -> int | float | str | None:
        value = self.coordinator.data.get(self.entity_description.key)
        return value.value if value is not None else None
