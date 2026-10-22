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

NETWORK_DEFAULTS = {
    CONF_BIND_HOST: "0.0.0.0",
    CONF_BIND_PORT: 4001,
    CONF_SOURCE_PORT: 0,
}
OPTION_DEFAULTS = {
    CONF_PROFILE: "observe_only",
    CONF_STALE_TIMEOUT: 120,
    CONF_PARTIAL_TIMEOUT: 1.0,
    CONF_GAP_TIMEOUT: 5.0,
}
