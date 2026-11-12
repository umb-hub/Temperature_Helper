"""Temperature Helper: creates native Home Assistant helpers for heating zones.

One config entry (added with a single click, no form). Each heating zone is
a config subentry ("Add zone"). On every load the integration reconciles
what exists with the configured zones:

* zone added / reconfigured -> its helpers, dashboard tiles, sensor in the
  average helper are created (each item only once: user deletions are
  respected across restarts unless "recreate_missing" is used);
* zone removed -> everything it created is deleted;
* integration removed -> everything it created is deleted (zone helpers,
  average and template helpers, dashboard, stored state).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .average_manager import (
    SharedState,
    async_add_sensor_to_average,
    async_backfill_template_once,
    async_ensure_template,
    async_remove_sensor_from_average,
    async_remove_shared_helpers,
    average_entity_id,
    shared_lock,
    template_entity_id,
)
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
    DATA_DASHBOARD_PLACED,
    DATA_HELPERS,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_STEP,
    DOMAIN,
    ENTRY_TITLE,
    INPUT_BOOLEAN,
    INPUT_NUMBER,
    MANUAL_SWITCH_ICON,
    MANUAL_SWITCH_KEY,
    MANUAL_SWITCH_LABEL,
    SETPOINT_TYPES,
    SUBENTRY_ZONE,
)
from .dashboard_manager import (
    _resolve_entity_id,
    async_add_zone_to_dashboard,
    async_delete_dashboard,
    async_remove_from_dashboard,
    dashboard_exists,
)
from .helper_manager import (
    HelperCollectionUnavailable,
    HelperSpec,
    async_create_helper,
    async_delete_helper,
    helper_exists,
)

_LOGGER = logging.getLogger(__name__)

# Zone settings kept in each subentry's data
ZONE_KEYS = (
    CONF_ZONE,
    CONF_SETPOINTS,
    CONF_MIN_TEMP,
    CONF_MAX_TEMP,
    CONF_STEP,
    CONF_MANUAL_SWITCH,
    CONF_TEMP_SENSOR,
)


# --------------------------------------------------------------------------- #
# Zone helpers                                                                #
# --------------------------------------------------------------------------- #


def build_specs(zone_cfg: Mapping[str, Any]) -> list[HelperSpec]:
    """Return the helpers a zone wants to exist."""
    zone: str = zone_cfg[CONF_ZONE]
    min_temp = float(zone_cfg.get(CONF_MIN_TEMP, DEFAULT_MIN_TEMP))
    max_temp = float(zone_cfg.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP))
    step = float(zone_cfg.get(CONF_STEP, DEFAULT_STEP))

    specs: list[HelperSpec] = []
    for key in zone_cfg.get(CONF_SETPOINTS, []):
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

    if zone_cfg.get(CONF_MANUAL_SWITCH, False):
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


async def _async_ensure_zone_helpers(
    hass: HomeAssistant,
    zone_cfg: Mapping[str, Any],
    record: dict[str, Any],
    recreate: bool,
) -> None:
    """Create missing helpers of a zone, never duplicating them.

    * tracked and present                 -> nothing to do
    * tracked but deleted by the user      -> respected, unless ``recreate``
    * not tracked, same id already exists  -> adopted (never deleted by us)
    * not tracked, missing                 -> created
    * tracked but deselected in the zone   -> deleted if we created it
    """
    tracked: dict[str, dict[str, Any]] = record.setdefault("helpers", {})
    specs = build_specs(zone_cfg)
    wanted = {spec.key for spec in specs}

    for key in [k for k in tracked if k not in wanted]:
        old = tracked.pop(key)
        entity_id = _resolve_entity_id(hass, old["domain"], old["id"])
        await async_remove_from_dashboard(hass, None, [entity_id])
        if old.get("created"):
            await async_delete_helper(hass, old["domain"], old["id"])
        record["placed"] = [p for p in record.get("placed", []) if p != key]

    for spec in specs:
        old = tracked.get(spec.key)
        if old and old.get("domain") == spec.domain:
            if helper_exists(hass, spec.domain, old["id"]) or not recreate:
                continue
        if helper_exists(hass, spec.domain, spec.suggested_id):
            tracked[spec.key] = {
                "domain": spec.domain,
                "id": spec.suggested_id,
                "created": bool(old and old.get("created")),
            }
            continue
        item_id = await async_create_helper(hass, spec)
        tracked[spec.key] = {"domain": spec.domain, "id": item_id, "created": True}


def _zone_entity_ids(hass: HomeAssistant, record: Mapping[str, Any]) -> list[str]:
    return [
        _resolve_entity_id(hass, h["domain"], h["id"])
        for h in record.get("helpers", {}).values()
    ]


async def _async_cleanup_zone(
    hass: HomeAssistant, shared: SharedState, record: Mapping[str, Any]
) -> None:
    """Delete everything a removed zone created."""
    await async_remove_from_dashboard(
        hass, record.get("zone"), _zone_entity_ids(hass, record)
    )
    for helper in record.get("helpers", {}).values():
        if helper.get("created"):
            await async_delete_helper(hass, helper["domain"], helper["id"])
    if sensor := record.get("sensor"):
        avg_before = average_entity_id(hass, shared.data.get("average_entry_id"))
        await async_remove_sensor_from_average(hass, shared, sensor)
        if avg_before and not shared.data.get("average_entry_id"):
            await async_remove_from_dashboard(hass, None, [avg_before])


# --------------------------------------------------------------------------- #
# Setup / reconcile                                                           #
# --------------------------------------------------------------------------- #


async def _async_reconcile(
    hass: HomeAssistant, entry: ConfigEntry, recreate: bool
) -> None:
    shared = await SharedState(hass).async_load()
    zones: dict[str, dict[str, Any]] = shared.data.setdefault("zones", {})
    subentries = {
        sid: sub
        for sid, sub in entry.subentries.items()
        if sub.subentry_type == SUBENTRY_ZONE
    }

    # 1) zones removed from the integration
    for sid in [sid for sid in zones if sid not in subentries]:
        try:
            await _async_cleanup_zone(hass, shared, zones[sid])
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unable to clean up zone %s", zones[sid].get("zone"))
        zones.pop(sid)

    # 2) shared template helper: once per installation
    if recreate or not shared.data.get("template_done"):
        try:
            await async_ensure_template(hass, shared)
            shared.data["template_done"] = True
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unable to create the template helper")
    try:
        async_backfill_template_once(hass, shared)
    except Exception:  # noqa: BLE001 - graph data is a nicety
        _LOGGER.exception("Unable to import past statistics for the template helper")

    use_dashboard = entry.options.get(CONF_DASHBOARD, True)

    # 3) configured zones (plus the shared graph, even with no zones)
    for sid, sub in subentries.items():
        cfg = sub.data
        record = zones.setdefault(sid, {})
        record["zone"] = cfg[CONF_ZONE]
        placed = set() if recreate else set(record.get("placed", []))

        await _async_ensure_zone_helpers(hass, cfg, record, recreate)

        sensor: str | None = cfg.get(CONF_TEMP_SENSOR) or None
        old_sensor = record.get("sensor")
        if old_sensor and old_sensor != sensor:
            placed.discard(f"avg:{old_sensor}")
            try:
                await async_remove_sensor_from_average(hass, shared, old_sensor)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unable to update the average helper")
        record["sensor"] = sensor
        if sensor and f"avg:{sensor}" not in placed:
            try:
                await async_add_sensor_to_average(hass, shared, sensor, recreate)
                placed.add(f"avg:{sensor}")
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unable to update the average helper")

        if use_dashboard:
            todo = {
                key: h
                for key, h in record["helpers"].items()
                if key not in placed and helper_exists(hass, h["domain"], h["id"])
            }
            if await _async_place(hass, shared, recreate, cfg[CONF_ZONE], todo):
                placed |= set(todo)
        record["placed"] = sorted(placed)

    if use_dashboard and not subentries:
        await _async_place(hass, shared, recreate, None, {})

    await shared.async_set()


async def _async_place(
    hass: HomeAssistant,
    shared: SharedState,
    recreate: bool,
    zone: str | None,
    todo: dict[str, dict[str, Any]],
) -> bool:
    """Put zone tiles and not-yet-placed shared helpers in the dashboard."""
    graph = [
        (flag, ent)
        for flag, ent in (
            ("graph_placed", average_entity_id(hass, shared.data.get("average_entry_id"))),
            (
                "template_graph_placed",
                template_entity_id(hass, shared.data.get("template_entry_id")),
            ),
        )
        if ent and (recreate or not shared.data.get(flag))
    ]
    if not todo and not graph:
        return True
    existed = dashboard_exists(hass)
    try:
        ok = await async_add_zone_to_dashboard(
            hass, zone or "", list(todo.values()), [e for _, e in graph]
        )
    except Exception:  # noqa: BLE001 - never break helpers because of the UI
        _LOGGER.exception("Unable to update the Temperature dashboard")
        return False
    if ok:
        for flag, _ in graph:
            shared.data[flag] = True
        if not existed and dashboard_exists(hass):
            shared.data["dashboard_created"] = True
    return ok


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Temperature Helper."""
    recreate = bool(entry.options.get(CONF_RECREATE_MISSING, False))
    try:
        async with shared_lock(hass):
            await _async_reconcile(hass, entry, recreate)
    except HelperCollectionUnavailable as err:
        raise ConfigEntryNotReady(str(err)) from err

    if recreate:
        # One-shot flag: clear it so later restarts respect user deletions again.
        hass.config_entries.async_update_entry(
            entry,
            options={k: v for k, v in entry.options.items() if k != CONF_RECREATE_MISSING},
        )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload on options or zone (subentry) changes -> reconcile."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload. Nothing to tear down: helpers live in Home Assistant."""
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Integration removed: delete everything it created."""
    if entry.entry_id in hass.data.get(DOMAIN, {}).get("merged", set()):
        return  # v1 entry merged into the v2 one during migration
    async with shared_lock(hass):
        shared = await SharedState(hass).async_load()
        for record in shared.data.get("zones", {}).values():
            try:
                await _async_cleanup_zone(hass, shared, record)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unable to clean up zone %s", record.get("zone"))
        try:
            await async_remove_shared_helpers(hass, shared)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unable to delete shared helpers")
        if shared.data.get("dashboard_created"):
            try:
                await async_delete_dashboard(hass)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unable to delete the dashboard")
        await shared.async_remove()
    _LOGGER.info("Temperature Helper removed together with everything it created")


# --------------------------------------------------------------------------- #
# Migration v1 (one entry per zone) -> v2 (one entry, zones as subentries)    #
# --------------------------------------------------------------------------- #


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Merge every v1 entry into a single v2 entry with one subentry per zone."""
    if entry.version >= 2:
        return True

    merged: set[str] = hass.data.setdefault(DOMAIN, {}).setdefault("merged", set())
    async with shared_lock(hass):
        if entry.entry_id in merged:
            return False  # already absorbed into the v2 entry; being removed

        main = next(
            (e for e in hass.config_entries.async_entries(DOMAIN) if e.version >= 2),
            None,
        )
        v1_entries = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.version < 2 and e.entry_id not in merged
        ]
        # Snapshot before touching any entry (the main one gets its data reset)
        snapshots = [
            (old, {**old.data, **old.options}, dict(old.data), old.unique_id)
            for old in v1_entries
        ]
        shared = await SharedState(hass).async_load()
        zones: dict[str, dict[str, Any]] = shared.data.setdefault("zones", {})

        if main is None:
            main = entry
            hass.config_entries.async_update_entry(
                entry,
                version=2,
                title=ENTRY_TITLE,
                unique_id=None,
                data={},
                options={
                    CONF_DASHBOARD: any(
                        cfg.get(CONF_DASHBOARD, True) for _, cfg, _, _ in snapshots
                    )
                },
            )

        for old, cfg, old_data, old_unique_id in snapshots:
            zone_data = {k: cfg[k] for k in ZONE_KEYS if k in cfg and cfg[k] != ""}
            sub = ConfigSubentry(
                data=zone_data,  # type: ignore[arg-type]
                subentry_type=SUBENTRY_ZONE,
                title=cfg[CONF_ZONE],
                unique_id=old_unique_id,
            )
            hass.config_entries.async_add_subentry(main, sub)
            zones[sub.subentry_id] = {
                "zone": cfg[CONF_ZONE],
                # v1 did not record created/adopted: treat as created
                "helpers": {
                    k: {**h, "created": True}
                    for k, h in old_data.get(DATA_HELPERS, {}).items()
                },
                "placed": [
                    p for p in old_data.get(DATA_DASHBOARD_PLACED, []) if p != "tpl"
                ],
                "sensor": cfg.get(CONF_TEMP_SENSOR) or None,
            }
            if old.entry_id != main.entry_id:
                merged.add(old.entry_id)
                hass.async_create_task(hass.config_entries.async_remove(old.entry_id))

        if shared.data.get("template_entry_id"):
            shared.data["template_done"] = True
        if shared.data.get("graph_placed") or shared.data.get("template_graph_placed"):
            shared.data["dashboard_created"] = True
        await shared.async_set()

    _LOGGER.info(
        "Migrated %d zone(s) into a single Temperature Helper entry", len(v1_entries)
    )
    return entry.entry_id == main.entry_id
