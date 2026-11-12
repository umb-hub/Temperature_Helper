"""Create/extend a native (storage mode) Lovelace dashboard.

Same approach as the helpers: we use the ``DashboardsCollection`` behind the
``lovelace/dashboards/*`` websocket commands, so the dashboard is identical to
one created from Settings → Dashboards: editable from the UI, persisted in
``.storage``, not owned by this integration (kept when it is removed).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    DASHBOARD_ICON,
    DASHBOARD_TITLE,
    DASHBOARD_URL_PATH,
    DASHBOARD_VIEW_PATH,
    INPUT_BOOLEAN,
    INPUT_NUMBER,
)
from .helper_manager import find_storage_collection

_LOGGER = logging.getLogger(__name__)

LOVELACE_DOMAIN = "lovelace"


def _dashboards(hass: HomeAssistant) -> dict[str | None, Any] | None:
    data = hass.data.get(LOVELACE_DOMAIN)
    return getattr(data, "dashboards", None)


def _resolve_entity_id(hass: HomeAssistant, domain: str, item_id: str) -> str:
    """Entity id of a collection helper (follows renames done by the user)."""
    return (
        er.async_get(hass).async_get_entity_id(domain, domain, item_id)
        or f"{domain}.{item_id}"
    )


def _referenced_entities(node: Any) -> set[str]:
    """All values of "entity"/"entities" keys anywhere in a dashboard config."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "entity" and isinstance(value, str):
                found.add(value)
            elif key == "entities" and isinstance(value, list):
                for ent in value:
                    if isinstance(ent, str):
                        found.add(ent)
                    elif isinstance(ent, dict) and isinstance(ent.get("entity"), str):
                        found.add(ent["entity"])
            else:
                found |= _referenced_entities(value)
    elif isinstance(node, list):
        for value in node:
            found |= _referenced_entities(value)
    return found


def _tile(entity_id: str) -> dict[str, Any]:
    if entity_id.startswith(f"{INPUT_BOOLEAN}."):
        return {
            "type": "tile",
            "entity": entity_id,
            "tap_action": {"action": "toggle"},
            "grid_options": {"columns": 12},
        }
    return {
        "type": "tile",
        "entity": entity_id,
        "features": [{"type": "numeric-input", "style": "buttons"}],
        "features_position": "bottom",
        "grid_options": {"columns": 12},
    }


def _zone_section(zone: str, entity_ids: list[str]) -> dict[str, Any]:
    return {
        "type": "grid",
        "cards": [
            {"type": "heading", "heading": zone, "icon": "mdi:home-thermometer"},
            *(_tile(e) for e in entity_ids),
        ],
    }


def _is_zone_section(section: Any, zone: str) -> bool:
    return isinstance(section, dict) and any(
        isinstance(c, dict) and c.get("type") == "heading" and c.get("heading") == zone
        for c in section.get("cards", [])
    )


def _empty_config() -> dict[str, Any]:
    return {
        "title": DASHBOARD_TITLE,
        "views": [
            {
                "title": DASHBOARD_TITLE,
                "path": DASHBOARD_VIEW_PATH,
                "icon": DASHBOARD_ICON,
                "type": "sections",
                "max_columns": 4,
                "sections": [],
            }
        ],
    }


async def async_add_zone_to_dashboard(
    hass: HomeAssistant, zone: str, helpers: list[dict[str, str]]
) -> bool:
    """Ensure the dashboard exists and shows these helpers for the zone.

    Returns True when done (or nothing to do), False if Lovelace is unavailable.
    Never modifies or removes what is already in the dashboard: helpers already
    referenced anywhere are skipped, the others are appended to the zone's
    section (matched by its heading) or to a new section.
    """
    dashboards = _dashboards(hass)
    if dashboards is None:
        _LOGGER.warning("Lovelace not loaded; dashboard not created")
        return False

    if DASHBOARD_URL_PATH not in dashboards:
        coll = find_storage_collection(
            hass, "lovelace/dashboards", "lovelace_dashboards"
        )
        await coll.async_create_item(
            {
                "url_path": DASHBOARD_URL_PATH,
                "title": DASHBOARD_TITLE,
                "icon": DASHBOARD_ICON,
                "show_in_sidebar": True,
                "require_admin": False,
            }
        )
        _LOGGER.info("Created dashboard /%s", DASHBOARD_URL_PATH)

    dashboard = dashboards.get(DASHBOARD_URL_PATH)
    if dashboard is None or getattr(dashboard, "mode", None) != "storage":
        _LOGGER.warning(
            "Dashboard /%s exists but is not editable (YAML); skipping",
            DASHBOARD_URL_PATH,
        )
        return True

    try:
        config = await dashboard.async_load(False)
    except Exception:  # noqa: BLE001 - ConfigNotFound: never saved yet
        config = None
    if not isinstance(config, dict) or not config.get("views"):
        config = _empty_config()
    else:
        config = {**config, "views": list(config["views"])}

    referenced = _referenced_entities(config)
    missing = [
        e
        for e in (_resolve_entity_id(hass, h["domain"], h["id"]) for h in helpers)
        if e not in referenced
    ]
    if not missing:
        return True

    views: list[dict[str, Any]] = config["views"]

    # 1) a section of this zone already exists -> append tiles to it
    for vi, view in enumerate(views):
        sections = view.get("sections")
        if not isinstance(sections, list):
            continue
        for si, section in enumerate(sections):
            if _is_zone_section(section, zone):
                new_sections = list(sections)
                new_sections[si] = {
                    **section,
                    "cards": [*section["cards"], *(_tile(e) for e in missing)],
                }
                views[vi] = {**view, "sections": new_sections}
                await dashboard.async_save(config)
                _LOGGER.info("Added %s to zone %s in dashboard", missing, zone)
                return True

    # 2) otherwise new section in our view / first sections view / new view
    index = next(
        (i for i, v in enumerate(views) if v.get("path") == DASHBOARD_VIEW_PATH),
        next((i for i, v in enumerate(views) if v.get("type") == "sections"), None),
    )
    if index is None:
        views.append(_empty_config()["views"][0])
        index = len(views) - 1
    view = {**views[index]}
    view["sections"] = [*view.get("sections", []), _zone_section(zone, missing)]
    views[index] = view

    await dashboard.async_save(config)
    _LOGGER.info("Added zone %s to dashboard /%s", zone, DASHBOARD_URL_PATH)
    return True
