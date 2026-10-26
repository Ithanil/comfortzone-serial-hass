"""UI flows exercised through Home Assistant's flow manager."""

from unittest.mock import patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.comfortzone_serial.const import DOMAIN, OPTION_DEFAULTS

pytestmark = pytest.mark.asyncio
NETWORK = {
    "source_ip": "192.0.2.10",
    "bind_host": "0.0.0.0",
    "bind_port": 4001,
    "source_port": 0,
}


async def test_user_default_ex35_polling_and_no_form_network_probe(hass):
    with patch("asyncio.BaseEventLoop.create_datagram_endpoint") as endpoint:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        with patch(
            "custom_components.comfortzone_serial.async_setup_entry", return_value=True
        ):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], NETWORK
            )
            await hass.async_block_till_done()
        endpoint.assert_not_called()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == NETWORK
    assert result["result"].unique_id is None
    assert result["result"].options == OPTION_DEFAULTS
    assert result["result"].minor_version == 3


@pytest.mark.parametrize(
    "change",
    [
        {"source_ip": "moxa.local"},
        {"source_ip": "0.0.0.0"},
        {"bind_host": "::1"},
        {"source_ip": "239.1.2.3"},
    ],
)
async def test_invalid_addresses(hass, change):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=NETWORK | change
    )
    assert result["errors"] == {"base": "invalid_network"}


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({}, "source_already_configured"),
        ({"source_ip": "192.0.2.11"}, "bind_conflict"),
        ({"source_ip": "192.0.2.11", "bind_host": "127.0.0.1"}, "bind_conflict"),
    ],
)
async def test_duplicates_and_overlapping_binds(hass, change, error):
    MockConfigEntry(domain=DOMAIN, data=NETWORK).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=NETWORK | change
    )
    assert result["errors"] == {"base": error}


async def test_reconfigure_preserves_identity_and_options(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=NETWORK, options={"stale_timeout": 30})
    entry.add_to_hass(hass)
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], NETWORK | {"source_ip": "192.0.2.12"}
        )
        reload.assert_called_once_with(entry.entry_id)
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["source_ip"] == "192.0.2.12"
    assert entry.options == {"stale_timeout": 30}


async def test_options_validate_related_timeouts_and_reload(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=NETWORK)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    options = {
        "profile": "czbridge_rx50_temperatures_v1",
        "polling_enabled": False,
        "stale_timeout": 30,
        "partial_timeout": 10,
        "gap_timeout": 5,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], options
    )
    assert result["errors"] == {"base": "invalid_options"}
    options["gap_timeout"] = 15
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], options
        )
        await hass.async_block_till_done()
        reload.assert_called_once_with(entry.entry_id)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == OPTION_DEFAULTS | options


async def test_broken_entry_does_not_prevent_valid_configuration(hass):
    MockConfigEntry(domain=DOMAIN, data={"source_ip": "broken"}).add_to_hass(hass)
    with patch(
        "custom_components.comfortzone_serial.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=NETWORK
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
