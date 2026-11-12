"""Create/extend a native (storage mode) Lovelace dashboard.

Same approach as the helpers: we use the ``DashboardsCollection`` behind the
``lovelace/dashboards/*`` websocket commands, so the dashboard is identical to
one created from Settings → Dashboards: editable from the UI, persisted in
``.storage``, not owned by this integration (kept when it is removed).
"""

from __future__ import annotations

import copy
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


def _view_index(views: list[dict[str, Any]]) -> int:
    """Our view, else first sections view, else a newly appended view."""
    index = next(
        (i for i, v in enumerate(views) if v.get("path") == DASHBOARD_VIEW_PATH),
        next((i for i, v in enumerate(views) if v.get("type") == "sections"), None),
    )
    if index is None:
        views.append(_empty_config()["views"][0])
        index = len(views) - 1
    views[index].setdefault("sections", [])
    return index


def _place_helpers(views: list[dict[str, Any]], zone: str, entity_ids: list[str]) -> None:
    """Append tiles to the zone's section, or add a new section for the zone."""
    for view in views:
        for section in view.get("sections") or []:
            if _is_zone_section(section, zone):
                section["cards"].extend(_tile(e) for e in entity_ids)
                return
    views[_view_index(views)]["sections"].append(_zone_section(zone, entity_ids))


def _place_graph(views: list[dict[str, Any]], entity_id: str) -> bool:
    """Put ``entity_id`` in the dashboard's statistics graph, once.

    Appended to the first existing statistics graph, otherwise a new graph
    without title is created at the top.
    """
    first_graph: dict[str, Any] | None = None
    for view in views:
        for section in view.get("sections") or []:
            for card in section.get("cards", []):
                if isinstance(card, dict) and card.get("type") == "statistics-graph":
                    if entity_id in _referenced_entities(card):
                        return False
                    if first_graph is None:
                        first_graph = card
    if first_graph is not None:
        first_graph.setdefault("entities", []).append(entity_id)
        return True

    graph = {
        "type": "statistics-graph",
        "entities": [entity_id],
        "chart_type": "line",
        "period": "hour",
        "days_to_show": 7,
        "stat_types": ["mean", "min", "max"],
        "grid_options": {"columns": "full"},
    }
    views[_view_index(views)]["sections"].insert(
        0, {"type": "grid", "column_span": 4, "cards": [graph]}
    )
    return True


async def async_add_zone_to_dashboard(
    hass: HomeAssistant,
    zone: str,
    helpers: list[dict[str, str]],
    graph_entities: list[str] | None = None,
) -> bool:
    """Ensure the dashboard exists and shows this zone's helpers (+ graph).

    Returns True when done (or nothing to do), False if Lovelace is unavailable.
    Never modifies or removes what the user has: helpers already referenced
    anywhere are skipped, the others are appended to the zone's section
    (matched by its heading) or to a new section. ``graph_entities`` go in
    the statistics graph without title at the top (legend = helpers' names).
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
        config = copy.deepcopy(await dashboard.async_load(False))
    except Exception:  # noqa: BLE001 - ConfigNotFound: never saved yet
        config = None
    if not isinstance(config, dict) or not config.get("views"):
        config = _empty_config()

    views: list[dict[str, Any]] = config["views"]
    changed = False

    referenced = _referenced_entities(config)
    missing = [
        e
        for e in (_resolve_entity_id(hass, h["domain"], h["id"]) for h in helpers)
        if e not in referenced
    ]
    if missing:
        _place_helpers(views, zone, missing)
        changed = True

    for graph_entity in graph_entities or []:
        if _place_graph(views, graph_entity):
            changed = True

    if changed:
        await dashboard.async_save(config)
        _LOGGER.info("Updated dashboard /%s for zone %s", DASHBOARD_URL_PATH, zone)
    return True
