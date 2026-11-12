"""Native "Combine the state of several sensors" (min_max) helper.

One helper for the whole installation: mean of the zones' temperature
sensors. Created and extended through the min_max config/options flows,
exactly like the UI does, so it is a normal helper the user can rename,
edit or delete from Settings → Helpers. It is not owned by this
integration and survives its removal.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import SOURCE_USER, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import AVERAGE_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

MIN_MAX = "min_max"
STORE_VERSION = 1
STORE_KEY = f"{DOMAIN}.shared"

# Shared (installation-wide) state:
#   average_entry_id: min_max config entry we created (None = never created)
#   graph_placed:     the statistics graph was added to the dashboard once


def shared_lock(hass: HomeAssistant) -> asyncio.Lock:
    """Lock serialising shared work (zones are set up concurrently at boot)."""
    data = hass.data.setdefault(DOMAIN, {})
    if "lock" not in data:
        data["lock"] = asyncio.Lock()
    return data["lock"]


class SharedState:
    """Persistent installation-wide state of this integration."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORE_VERSION, STORE_KEY)
        self.data: dict[str, Any] = {}

    async def async_load(self) -> SharedState:
        self.data = await self._store.async_load() or {}
        return self

    async def async_set(self, **changes: Any) -> None:
        self.data.update(changes)
        await self._store.async_save(self.data)


def average_entity_id(hass: HomeAssistant, entry_id: str | None) -> str | None:
    """Current entity id of the average helper (follows user renames)."""
    if not entry_id or hass.config_entries.async_get_entry(entry_id) is None:
        return None
    return er.async_get(hass).async_get_entity_id("sensor", MIN_MAX, entry_id)


async def async_add_sensor_to_average(
    hass: HomeAssistant, shared: SharedState, sensor: str, recreate: bool
) -> None:
    """Make sure ``sensor`` is part of the average helper (create it if needed)."""
    entry_id: str | None = shared.data.get("average_entry_id")
    entry: ConfigEntry | None = (
        hass.config_entries.async_get_entry(entry_id) if entry_id else None
    )

    if entry is None:
        if entry_id and not recreate:
            _LOGGER.debug("Average helper was deleted by the user; not recreating")
            return
        result = await hass.config_entries.flow.async_init(
            MIN_MAX, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "name": AVERAGE_NAME,
                "entity_ids": [sensor],
                "type": "mean",
                "round_digits": 1,
            },
        )
        if result["type"] is not FlowResultType.CREATE_ENTRY:
            _LOGGER.warning("Unable to create average helper: %s", result)
            return
        await shared.async_set(average_entry_id=result["result"].entry_id)
        _LOGGER.info("Created average helper '%s'", AVERAGE_NAME)
        return

    entity_ids: list[str] = list(entry.options.get("entity_ids", []))
    if sensor in entity_ids:
        return
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "entity_ids": [*entity_ids, sensor],
            "type": entry.options.get("type", "mean"),
            "round_digits": entry.options.get("round_digits", 1),
        },
    )
    _LOGGER.info("Added %s to average helper", sensor)
