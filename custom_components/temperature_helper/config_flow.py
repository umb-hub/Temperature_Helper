"""Config flow for Temperature Helper."""

from __future__ import annotations

from typing import Any

try:  # Home Assistant >= 2026 replaced voluptuous with probatio
    import probatio as vol
except ImportError:  # pragma: no cover - older Home Assistant
    import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    CONF_DASHBOARD,
    CONF_MANUAL_SWITCH,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_RECREATE_MISSING,
    CONF_SETPOINTS,
    CONF_STEP,
    CONF_TEMP_SENSOR,
    CONF_ZONE,
    DATA_HELPERS,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_SETPOINTS,
    DEFAULT_STEP,
    DOMAIN,
    SETPOINT_TYPES,
)

TEMP_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=-20, max=50, step=0.5, unit_of_measurement="°C",
        mode=selector.NumberSelectorMode.BOX,
    )
)
STEP_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0.1, max=5, step=0.1, unit_of_measurement="°C",
        mode=selector.NumberSelectorMode.BOX,
    )
)
SETPOINT_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=list(SETPOINT_TYPES),
        multiple=True,
        mode=selector.SelectSelectorMode.LIST,
        translation_key="setpoints",
    )
)


def _settings_schema(defaults: dict[str, Any]) -> dict:
    return {
        vol.Required(
            CONF_SETPOINTS, default=defaults.get(CONF_SETPOINTS, DEFAULT_SETPOINTS)
        ): SETPOINT_SELECTOR,
        vol.Required(
            CONF_MIN_TEMP, default=defaults.get(CONF_MIN_TEMP, DEFAULT_MIN_TEMP)
        ): TEMP_SELECTOR,
        vol.Required(
            CONF_MAX_TEMP, default=defaults.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP)
        ): TEMP_SELECTOR,
        vol.Required(
            CONF_STEP, default=defaults.get(CONF_STEP, DEFAULT_STEP)
        ): STEP_SELECTOR,
        vol.Required(
            CONF_MANUAL_SWITCH, default=defaults.get(CONF_MANUAL_SWITCH, True)
        ): selector.BooleanSelector(),
        vol.Required(
            CONF_DASHBOARD, default=defaults.get(CONF_DASHBOARD, True)
        ): selector.BooleanSelector(),
        **_sensor_field(defaults.get(CONF_TEMP_SENSOR)),
    }


def _sensor_field(current: str | None) -> dict:
    """Optional temperature sensor; suggested_value keeps it clearable."""
    return {
        vol.Optional(
            CONF_TEMP_SENSOR,
            description={"suggested_value": current} if current else None,
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
        )
    }


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if float(user_input[CONF_MIN_TEMP]) >= float(user_input[CONF_MAX_TEMP]):
        errors["base"] = "min_max"
    elif not user_input.get(CONF_SETPOINTS) and not user_input.get(CONF_MANUAL_SWITCH):
        errors["base"] = "nothing_selected"
    return errors


class TemperatureHelperConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow: one entry per zone."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            zone = user_input[CONF_ZONE].strip()
            if not zone:
                errors[CONF_ZONE] = "zone_required"
            else:
                await self.async_set_unique_id(slugify(zone))
                self._abort_if_unique_id_configured()
                errors = _validate(user_input)
                if not errors:
                    return self.async_create_entry(
                        title=zone,
                        data={**user_input, CONF_ZONE: zone, DATA_HELPERS: {}},
                    )

        schema = {
            vol.Required(
                CONF_ZONE, default=(user_input or {}).get(CONF_ZONE, "")
            ): selector.TextSelector(),
            **_settings_schema(user_input or {}),
        }
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema(schema), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TemperatureHelperOptionsFlow()


class TemperatureHelperOptionsFlow(OptionsFlow):
    """Change which helpers exist for the zone (new ones get created on save)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                # Explicit "" so a cleared sensor overrides the one in entry.data
                return self.async_create_entry(
                    data={CONF_TEMP_SENSOR: "", **user_input}
                )

        current = {**self.config_entry.data, **self.config_entry.options}
        schema = {
            **_settings_schema(user_input or current),
            vol.Required(CONF_RECREATE_MISSING, default=False): selector.BooleanSelector(),
        }
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(schema), errors=errors
        )
