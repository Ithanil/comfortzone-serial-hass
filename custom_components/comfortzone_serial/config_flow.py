"""Local acquisition configuration; forms never probe or configure the pump."""

from __future__ import annotations

from typing import Any

import probatio as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

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
    DOMAIN,
    NAME,
    NETWORK_DEFAULTS,
    OPTION_DEFAULTS,
)
from .settings import DecoderSettings, network_settings
from .telemetry.decoder import DecoderProfile
from .telemetry.queries import READS_BY_NAME
from .telemetry.udp import NetworkSettings


def _network_schema(*, setup: bool = False) -> vol.Schema:
    fields = {
        vol.Required(CONF_SOURCE_IP): str,
        vol.Required(CONF_BIND_HOST, default=NETWORK_DEFAULTS[CONF_BIND_HOST]): str,
        vol.Required(CONF_BIND_PORT, default=NETWORK_DEFAULTS[CONF_BIND_PORT]): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Required(
            CONF_SOURCE_PORT, default=NETWORK_DEFAULTS[CONF_SOURCE_PORT]
        ): vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
    }
    if setup:
        fields[
            vol.Optional(
                CONF_POLLING_ENABLED, default=OPTION_DEFAULTS[CONF_POLLING_ENABLED]
            )
        ] = bool
    return vol.Schema(fields)


def _options_schema(options: dict) -> vol.Schema:
    values = OPTION_DEFAULTS | options
    return vol.Schema(
        {
            vol.Required(
                CONF_PROFILE, default=values[CONF_PROFILE]
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[profile.value for profile in DecoderProfile],
                    translation_key="profile",
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_READ_QUERIES, default=values[CONF_READ_QUERIES]
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(READS_BY_NAME),
                    multiple=True,
                    translation_key="read_queries",
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Required(
                CONF_STALE_TIMEOUT, default=values[CONF_STALE_TIMEOUT]
            ): vol.All(vol.Coerce(float), vol.Range(min=5, max=86400)),
            vol.Required(
                CONF_PARTIAL_TIMEOUT, default=values[CONF_PARTIAL_TIMEOUT]
            ): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=60)),
            vol.Required(CONF_GAP_TIMEOUT, default=values[CONF_GAP_TIMEOUT]): vol.All(
                vol.Coerce(float), vol.Range(min=0.01, max=3600)
            ),
            vol.Optional(
                CONF_POLLING_ENABLED, default=values[CONF_POLLING_ENABLED]
            ): bool,
            vol.Optional(
                CONF_POLL_INTERVAL, default=values[CONF_POLL_INTERVAL]
            ): vol.All(
                vol.Coerce(float), vol.Range(min=0, min_included=False, max=3600)
            ),
            vol.Optional(
                CONF_REQUEST_DELAY, default=values[CONF_REQUEST_DELAY]
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=3600)),
            vol.Optional(
                CONF_DESTINATION_PORT, default=values[CONF_DESTINATION_PORT]
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Optional(CONF_PUMP_ADDRESS, default=values[CONF_PUMP_ADDRESS]): str,
        }
    )


class ComfortZoneConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a receiver entry; its entry ID is the persistent local identity."""

    VERSION = 1
    MINOR_VERSION = 3

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ComfortZoneOptionsFlow:
        return ComfortZoneOptionsFlow()

    def _conflict(self, settings: NetworkSettings, exclude: str | None) -> str | None:
        for entry in self._async_current_entries():
            if entry.entry_id == exclude:
                continue
            try:
                other = network_settings(entry.data)
            except (ValueError, KeyError, TypeError):
                # A broken persisted entry cannot bind and must not prevent the
                # user repairing or creating another valid receiver.
                continue
            if settings.source_ip == other.source_ip and (
                settings.source_port is None
                or other.source_port is None
                or settings.source_port == other.source_port
            ):
                return "source_already_configured"
            if settings.bind_port == other.bind_port and (
                settings.bind_host == "0.0.0.0"
                or other.bind_host == "0.0.0.0"
                or settings.bind_host == other.bind_host
            ):
                return "bind_conflict"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._network_step("user", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._network_step("reconfigure", user_input)

    async def _network_step(
        self, step: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry() if step == "reconfigure" else None
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                settings = network_settings(user_input)
                conflict = self._conflict(settings, entry.entry_id if entry else None)
            except (ValueError, KeyError, TypeError):
                errors["base"] = "invalid_network"
            else:
                if conflict:
                    errors["base"] = conflict
                elif entry:
                    return self.async_update_reload_and_abort(entry, data=user_input)
                else:
                    # No serial/MAC identity has been learned from passive traffic.
                    # Do not pretend the sender IP is an immutable device ID.
                    data = dict(user_input)
                    enabled = data.pop(
                        CONF_POLLING_ENABLED, OPTION_DEFAULTS[CONF_POLLING_ENABLED]
                    )
                    return self.async_create_entry(
                        title=NAME,
                        data=data,
                        options=OPTION_DEFAULTS | {CONF_POLLING_ENABLED: enabled},
                    )
        defaults = user_input if user_input is not None else entry.data if entry else {}
        return self.async_show_form(
            step_id=step,
            data_schema=self.add_suggested_values_to_schema(
                _network_schema(setup=entry is None), defaults
            ),
            errors=errors,
        )


class ComfortZoneOptionsFlow(OptionsFlowWithReload):
    """Select individual reads, cycle timing and receive/freshness limits."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                DecoderSettings.from_options(user_input)
            except (ValueError, TypeError):
                errors["base"] = "invalid_options"
            else:
                return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _options_schema(dict(self.config_entry.options)),
                user_input if user_input is not None else self.config_entry.options,
            ),
            errors=errors,
        )
