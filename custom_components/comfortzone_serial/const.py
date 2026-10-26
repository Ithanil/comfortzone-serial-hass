"""Integration settings, independent of Home Assistant imports."""

DOMAIN = "comfortzone_serial"
NAME = "ComfortZone Serial"
CONF_SOURCE_IP = "source_ip"
CONF_BIND_HOST = "bind_host"
CONF_BIND_PORT = "bind_port"
CONF_SOURCE_PORT = "source_port"
CONF_PROFILE = "profile"
CONF_STALE_TIMEOUT = "stale_timeout"
CONF_PARTIAL_TIMEOUT = "partial_timeout"
CONF_GAP_TIMEOUT = "gap_timeout"
CONF_POLLING_ENABLED = "polling_enabled"
CONF_POLL_INTERVAL = "poll_interval"
CONF_DESTINATION_PORT = "destination_port"
CONF_PUMP_ADDRESS = "pump_address"
CONF_READ_QUERIES = "read_queries"
CONF_REQUEST_DELAY = "request_delay"

DEFAULT_READ_QUERIES = (
    "temperature",
    "power",
    "counters",
    "heating_settings",
    "hot_water_settings",
)

NETWORK_DEFAULTS = {
    CONF_BIND_HOST: "0.0.0.0",
    CONF_BIND_PORT: 4001,
    CONF_SOURCE_PORT: 4001,
}
OPTION_DEFAULTS = {
    CONF_PROFILE: "ex35_0b15_temperatures_v1",
    CONF_STALE_TIMEOUT: 120,
    CONF_PARTIAL_TIMEOUT: 1.0,
    CONF_GAP_TIMEOUT: 5.0,
    CONF_POLLING_ENABLED: True,
    CONF_POLL_INTERVAL: 60.0,
    CONF_DESTINATION_PORT: 4001,
    CONF_PUMP_ADDRESS: "656fde02",
    CONF_READ_QUERIES: list(DEFAULT_READ_QUERIES),
    CONF_REQUEST_DELAY: 0.25,
}
