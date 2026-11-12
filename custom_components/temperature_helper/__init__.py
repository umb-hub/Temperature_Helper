"""Temperature Helper: creates native Home Assistant helpers for heating zones."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_MANUAL_SWITCH,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_RECREATE_MISSING,
    CONF_SETPOINTS,
    CONF_STEP,
    CONF_ZONE,
    DATA_HELPERS,
    INPUT_BOOLEAN,
    INPUT_NUMBER,
    MANUAL_SWITCH_ICON,
    MANUAL_SWITCH_KEY,
    MANUAL_SWITCH_LABEL,
    SETPOINT_TYPES,
)
from .helper_manager import (
    HelperCollectionUnavailable,
    HelperSpec,
    async_create_helper,
    helper_exists,
)

_LOGGER = logging.getLogger(__name__)


def _option(entry: ConfigEntry, key: str, default: Any = None) -> Any:
    """Options override data."""
    return entry.options.get(key, entry.data.get(key, default))


def build_specs(entry: ConfigEntry) -> list[HelperSpec]:
    """Return the helpers this entry wants to exist."""
    zone: str = entry.data[CONF_ZONE]
    min_temp = float(_option(entry, CONF_MIN_TEMP))
    max_temp = float(_option(entry, CONF_MAX_TEMP))
    step = float(_option(entry, CONF_STEP))

    specs: list[HelperSpec] = []
    for key in _option(entry, CONF_SETPOINTS, []):
        sp = SETPOINT_TYPES.get(key)
        if sp is None:
            continue
        specs.append(
            HelperSpec(
                key=key,
                domain=INPUT_NUMBER,
                data={
                    "name": f"{zone} {sp.label}",
                    "min": min_temp,
                    "max": max_temp,
                    "step": step,
                    "initial": min(max(sp.default, min_temp), max_temp),
                    "mode": "box",
                    "unit_of_measurement": "°C",
                    "icon": sp.icon,
                },
            )
        )

    if _option(entry, CONF_MANUAL_SWITCH, False):
        specs.append(
            HelperSpec(
                key=MANUAL_SWITCH_KEY,
                domain=INPUT_BOOLEAN,
                data={
                    "name": f"{zone} {MANUAL_SWITCH_LABEL}",
                    "icon": MANUAL_SWITCH_ICON,
                },
            )
        )
    return specs


async def async_ensure_helpers(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Create missing helpers without ever duplicating them.

    Rules per helper:
    * already tracked and still present  -> nothing to do
    * tracked but deleted by the user     -> respected (not recreated),
                                             unless "recreate_missing" is set
    * not tracked, same id already exists -> adopted (tracked, not created)
    * not tracked, does not exist         -> created and tracked
    """
    tracked: dict[str, dict[str, str]] = dict(entry.data.get(DATA_HELPERS, {}))
    recreate = bool(entry.options.get(CONF_RECREATE_MISSING, False))
    changed = False

    for spec in build_specs(entry):
        record = tracked.get(spec.key)

        if record and record.get("domain") == spec.domain:
            if helper_exists(hass, spec.domain, record["id"]):
                continue
            if not recreate:
                _LOGGER.debug(
                    "Helper %s.%s was removed by the user; not recreating",
                    spec.domain,
                    record["id"],
                )
                continue

        if helper_exists(hass, spec.domain, spec.suggested_id):
            item_id = spec.suggested_id
            _LOGGER.info("Adopting existing helper %s.%s", spec.domain, item_id)
        else:
            item_id = await async_create_helper(hass, spec)

        tracked[spec.key] = {"domain": spec.domain, "id": item_id}
        changed = True

    if changed:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, DATA_HELPERS: tracked}
        )

    if recreate:
        # One-shot flag: clear it so later restarts respect user deletions again.
        hass.config_entries.async_update_entry(
            entry,
            options={k: v for k, v in entry.options.items() if k != CONF_RECREATE_MISSING},
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Temperature Helper from a config entry."""
    try:
        await async_ensure_helpers(hass, entry)
    except HelperCollectionUnavailable as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change (creates newly enabled helpers)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry. Helpers are native and stay untouched."""
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Integration removed: helpers are intentionally NOT deleted."""
    _LOGGER.info(
        "Temperature Helper entry '%s' removed; its helpers are kept: %s",
        entry.title,
        ", ".join(
            f"{h['domain']}.{h['id']}" for h in entry.data.get(DATA_HELPERS, {}).values()
        )
        or "none",
    )
