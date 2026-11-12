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
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
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
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_SETPOINTS,
    DEFAULT_STEP,
    DOMAIN,
    ENTRY_TITLE,
    SETPOINT_TYPES,
    SUBENTRY_ZONE,
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


def _zone_schema(defaults: dict[str, Any]) -> dict:
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
        # suggested_value (not default) keeps the field clearable
        vol.Optional(
            CONF_TEMP_SENSOR,
            description=(
                {"suggested_value": defaults[CONF_TEMP_SENSOR]}
                if defaults.get(CONF_TEMP_SENSOR)
                else None
            ),
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
        ),
    }


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if float(user_input[CONF_MIN_TEMP]) >= float(user_input[CONF_MAX_TEMP]):
        errors["base"] = "min_max"
    elif not user_input.get(CONF_SETPOINTS) and not user_input.get(CONF_MANUAL_SWITCH):
        errors["base"] = "nothing_selected"
    return errors


class TemperatureHelperConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single click, no form: zones are added afterwards as subentries."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        return self.async_create_entry(title=ENTRY_TITLE, data={})

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_ZONE: ZoneSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TemperatureHelperOptionsFlow()


class ZoneSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure a heating zone."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            zone = user_input[CONF_ZONE].strip()
            unique_id = slugify(zone)
            if not zone:
                errors[CONF_ZONE] = "zone_required"
            elif any(
                sub.unique_id == unique_id
                for sub in self._get_entry().subentries.values()
            ):
                return self.async_abort(reason="already_configured")
            else:
                errors = _validate(user_input)
                if not errors:
                    return self.async_create_entry(
                        title=zone,
                        data={**user_input, CONF_ZONE: zone},
                        unique_id=unique_id,
                    )

        schema = {
            vol.Required(
                CONF_ZONE, default=(user_input or {}).get(CONF_ZONE, "")
            ): selector.TextSelector(),
            **_zone_schema(user_input or {}),
        }
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema(schema), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    data={**user_input, CONF_ZONE: subentry.data[CONF_ZONE]},
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(_zone_schema(user_input or dict(subentry.data))),
            errors=errors,
            description_placeholders={"zone": subentry.title},
        )


class TemperatureHelperOptionsFlow(OptionsFlow):
    """Global options: dashboard on/off, recreate what the user deleted."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        schema = {
            vol.Required(
                CONF_DASHBOARD,
                default=self.config_entry.options.get(CONF_DASHBOARD, True),
            ): selector.BooleanSelector(),
            vol.Required(CONF_RECREATE_MISSING, default=False): selector.BooleanSelector(),
        }
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
