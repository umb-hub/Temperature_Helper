"""Create native Home Assistant helpers (input_number / input_boolean).

Home Assistant does not expose a public Python API to create UI-managed
helpers. The UI creates them through the websocket commands
``<domain>/create``, which are bound methods of a
``StorageCollectionWebsocket`` holding the helper ``StorageCollection``.

We locate that same StorageCollection and call ``async_create_item`` on it,
so the result is *exactly* what the UI produces: an item persisted in
``.storage/<domain>``, editable/deletable from Settings → Helpers, not owned
by this integration's config entry (so it survives removal of the
integration).
"""

from __future__ import annotations

import gc
import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import collection, entity_registry as er
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

WEBSOCKET_DOMAIN = "websocket_api"


class HelperCollectionUnavailable(Exception):
    """Raised when the helper storage collection cannot be located."""


@dataclass(slots=True)
class HelperSpec:
    """A helper that should exist."""

    key: str
    domain: str
    data: dict[str, Any]

    @property
    def suggested_id(self) -> str:
        """Object id Home Assistant will derive from the name."""
        return slugify(self.data["name"])


def _from_websocket(hass: HomeAssistant, ws_prefix: str) -> collection.StorageCollection | None:
    """Find the collection through the registered ``<ws_prefix>/create`` handler."""
    handlers = hass.data.get(WEBSOCKET_DOMAIN)
    if not isinstance(handlers, dict):
        return None
    registered = handlers.get(f"{ws_prefix}/create")
    if not registered:
        return None

    func: Any = registered[0]
    # Handler is wrapped by require_admin(async_response(bound_method)),
    # both using functools.wraps -> follow __wrapped__ to the bound method.
    for _ in range(10):
        owner = getattr(func, "__self__", None)
        storage = getattr(owner, "storage_collection", None)
        if isinstance(storage, collection.StorageCollection):
            return storage
        func = getattr(func, "__wrapped__", None)
        if func is None:
            break
    return None


def _from_gc(store_key: str) -> collection.StorageCollection | None:
    """Fallback: scan live objects for the collection backed by ``.storage/<store_key>``."""
    for obj in gc.get_objects():
        if isinstance(obj, collection.StorageCollection):
            store = getattr(obj, "store", None)
            if getattr(store, "key", None) == store_key:
                return obj
    return None


def find_storage_collection(
    hass: HomeAssistant, ws_prefix: str, store_key: str
) -> collection.StorageCollection:
    """Return the StorageCollection the frontend uses via ``<ws_prefix>/*``."""
    storage = _from_websocket(hass, ws_prefix) or _from_gc(store_key)
    if storage is None:
        raise HelperCollectionUnavailable(
            f"Unable to locate storage collection for '{ws_prefix}'"
        )
    return storage


def get_storage_collection(hass: HomeAssistant, domain: str) -> collection.StorageCollection:
    """Return the StorageCollection used by the UI for ``domain`` helpers."""
    return find_storage_collection(hass, domain, domain)


def helper_exists(hass: HomeAssistant, domain: str, item_id: str) -> bool:
    """Return True if a helper with this id already exists (storage or YAML)."""
    if item_id in get_storage_collection(hass, domain).data:
        return True
    entity_id = f"{domain}.{item_id}"
    if hass.states.get(entity_id) is not None:
        return True
    return er.async_get(hass).async_get(entity_id) is not None


async def async_create_helper(hass: HomeAssistant, spec: HelperSpec) -> str:
    """Create the helper and return its item id."""
    storage = get_storage_collection(hass, spec.domain)
    item = await storage.async_create_item(dict(spec.data))
    item_id: str = item["id"]
    _LOGGER.info("Created helper %s.%s", spec.domain, item_id)
    return item_id


async def async_delete_helper(hass: HomeAssistant, domain: str, item_id: str) -> None:
    """Delete a UI-managed helper (no-op if it is already gone)."""
    storage = get_storage_collection(hass, domain)
    if item_id in storage.data:
        await storage.async_delete_item(item_id)
        _LOGGER.info("Deleted helper %s.%s", domain, item_id)
