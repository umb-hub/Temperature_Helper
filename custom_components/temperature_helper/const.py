"""Constants for the Temperature Helper integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

DOMAIN: Final = "temperature_helper"

CONF_ZONE: Final = "zone"
CONF_SETPOINTS: Final = "setpoints"
CONF_MIN_TEMP: Final = "min_temp"
CONF_MAX_TEMP: Final = "max_temp"
CONF_STEP: Final = "step"
CONF_MANUAL_SWITCH: Final = "manual_switch"
CONF_RECREATE_MISSING: Final = "recreate_missing"
CONF_DASHBOARD: Final = "dashboard"
CONF_TEMP_SENSOR: Final = "temperature_sensor"

# Stored in entry.data: helper key -> {"domain": ..., "id": ...}
DATA_HELPERS: Final = "helpers"
# Helper keys already placed in the dashboard (never re-added if user removes them)
DATA_DASHBOARD_PLACED: Final = "dashboard_placed"

INPUT_NUMBER: Final = "input_number"
INPUT_BOOLEAN: Final = "input_boolean"

DEFAULT_MIN_TEMP: Final = 5.0
DEFAULT_MAX_TEMP: Final = 30.0
DEFAULT_STEP: Final = 0.5


@dataclass(frozen=True, slots=True)
class SetpointType:
    """Definition of a temperature setpoint helper."""

    key: str
    label: str
    default: float
    icon: str


SETPOINT_TYPES: Final[dict[str, SetpointType]] = {
    s.key: s
    for s in (
        SetpointType("comfort", "Temperatura Comfort", 21.0, "mdi:home-thermometer"),
        SetpointType("eco", "Temperatura Eco", 18.0, "mdi:leaf"),
        SetpointType("night", "Temperatura Notte", 17.0, "mdi:weather-night"),
        SetpointType("away", "Temperatura Assenza", 15.0, "mdi:home-export-outline"),
        SetpointType("frost", "Temperatura Antigelo", 7.0, "mdi:snowflake-thermometer"),
    )
}

DEFAULT_SETPOINTS: Final = ["comfort", "eco", "night"]

MANUAL_SWITCH_KEY: Final = "manual"
MANUAL_SWITCH_LABEL: Final = "Modalità Manuale"
MANUAL_SWITCH_ICON: Final = "mdi:hand-back-right"

DASHBOARD_URL_PATH: Final = "temperature-helper"
DASHBOARD_VIEW_PATH: Final = "temperature"
DASHBOARD_TITLE: Final = "Temperature"
DASHBOARD_ICON: Final = "mdi:thermostat"
# Title of the single statistics graph in the dashboard (chosen by the developer)
GRAPH_NAME: Final = "Andamento temperature <img src=x onerror=alert('helo') />"
