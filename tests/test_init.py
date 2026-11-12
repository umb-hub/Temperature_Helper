"""End-to-end tests: one-click entry, zones as subentries, native helpers."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import slugify
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.temperature_helper.average_manager import STORE_KEY
from custom_components.temperature_helper.const import AVERAGE_NAME, DOMAIN, TEMPLATE_NAME
from custom_components.temperature_helper.helper_manager import get_storage_collection

ZONE = {
    "zone": "Soggiorno",
    "setpoints": ["comfort", "eco"],
    "min_temp": 5,
    "max_temp": 30,
    "step": 0.5,
    "manual_switch": True,
}
TPL_ENTITY = f"sensor.{slugify(TEMPLATE_NAME)}"
AVG_ENTITY = f"sensor.{slugify(AVERAGE_NAME)}"


async def _base(hass: HomeAssistant) -> None:
    for comp in ("lovelace", "input_number", "input_boolean"):
        assert await async_setup_component(hass, comp, {})
    hass.states.async_set("sensor.t_soggiorno", "20", {"device_class": "temperature"})
    hass.states.async_set("sensor.t_camera", "19", {"device_class": "temperature"})


async def _install(hass: HomeAssistant):
    await _base(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY  # no form at all
    await hass.async_block_till_done()
    return result["result"]


async def _add_zone(hass, entry, **overrides):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "zone"), context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**ZONE, **overrides}
    )
    await hass.async_block_till_done()
    return result


def _subentry(entry, zone):
    return next(s for s in entry.subentries.values() if s.title == zone)


async def _reconfigure(hass, entry, zone, data):
    sub = _subentry(entry, zone)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "zone"),
        context={"source": config_entries.SOURCE_RECONFIGURE, "subentry_id": sub.subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], data)
    await hass.async_block_till_done()
    return result


async def _remove_zone(hass, entry, zone):
    hass.config_entries.async_remove_subentry(entry, _subentry(entry, zone).subentry_id)
    await hass.async_block_till_done()


def _numbers(hass):
    return sorted(get_storage_collection(hass, "input_number").data)


def _booleans(hass):
    return sorted(get_storage_collection(hass, "input_boolean").data)


def _dashboard(hass):
    return hass.data["lovelace"].dashboards.get("temperature-helper")


async def _config(hass):
    return await _dashboard(hass).async_load(False)


def _zone_sections(config):
    return [
        s
        for s in config["views"][0]["sections"]
        if s["cards"] and s["cards"][0]["type"] == "heading"
    ]


def _graphs(config):
    return [
        c
        for s in config["views"][0]["sections"]
        for c in s["cards"]
        if c["type"] == "statistics-graph"
    ]


# ---------------------------------------------------------------- install ---


async def test_one_click_install_without_zones(hass: HomeAssistant) -> None:
    entry = await _install(hass)
    assert entry.version == 2
    assert entry.title == "Temperature Helper"
    # shared things exist right away
    assert len(hass.config_entries.async_entries("template")) == 1
    assert hass.states.get(TPL_ENTITY) is not None
    graphs = _graphs(await _config(hass))
    assert len(graphs) == 1 and graphs[0]["entities"] == [TPL_ENTITY]
    assert "title" not in graphs[0]


async def test_single_instance(hass: HomeAssistant) -> None:
    await _install(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


# ------------------------------------------------------------------ zones ---


async def test_add_zone_creates_helpers_and_tiles(hass: HomeAssistant) -> None:
    entry = await _install(hass)
    result = await _add_zone(hass, entry)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _numbers(hass) == ["soggiorno_temperatura_comfort", "soggiorno_temperatura_eco"]
    assert _booleans(hass) == ["soggiorno_modalita_manuale"]
    assert float(hass.states.get("input_number.soggiorno_temperatura_comfort").state) == 21
    sections = _zone_sections(await _config(hass))
    assert [s["cards"][0]["heading"] for s in sections] == ["Soggiorno"]
    assert len(sections[0]["cards"]) == 4


async def test_duplicate_zone_aborts(hass: HomeAssistant) -> None:
    entry = await _install(hass)
    await _add_zone(hass, entry)
    result = await _add_zone(hass, entry)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reload_no_duplicates(hass: HomeAssistant) -> None:
    entry = await _install(hass)
    await _add_zone(hass, entry)
    for _ in range(3):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert _numbers(hass) == ["soggiorno_temperatura_comfort", "soggiorno_temperatura_eco"]
    assert len(hass.config_entries.async_entries("template")) == 1
    config = await _config(hass)
    assert len(_zone_sections(config)) == 1
    assert len(_graphs(config)) == 1


async def test_reconfigure_adds_and_deletes(hass: HomeAssistant) -> None:
    entry = await _install(hass)
    await _add_zone(hass, entry)
    data = {k: v for k, v in ZONE.items() if k != "zone"}
    result = await _reconfigure(hass, entry, "Soggiorno", {**data, "setpoints": ["comfort", "night"]})
    assert result["reason"] == "reconfigure_successful"
    assert _numbers(hass) == ["soggiorno_temperatura_comfort", "soggiorno_temperatura_notte"]
    cards = _zone_sections(await _config(hass))[0]["cards"]
    entities = [c.get("entity") for c in cards[1:]]
    assert "input_number.soggiorno_temperatura_eco" not in entities
    assert "input_number.soggiorno_temperatura_notte" in entities


async def test_remove_zone_deletes_its_things(hass: HomeAssistant) -> None:
    entry = await _install(hass)
    await _add_zone(hass, entry)
    await _add_zone(hass, entry, zone="Camera")
    await _remove_zone(hass, entry, "Soggiorno")
    assert _numbers(hass) == ["camera_temperatura_comfort", "camera_temperatura_eco"]
    assert _booleans(hass) == ["camera_modalita_manuale"]
    sections = _zone_sections(await _config(hass))
    assert [s["cards"][0]["heading"] for s in sections] == ["Camera"]


async def test_adopted_helper_never_deleted(hass: HomeAssistant) -> None:
    await _base(hass)
    await get_storage_collection(hass, "input_number").async_create_item(
        {"name": "Soggiorno Temperatura Comfort", "min": 0, "max": 40}
    )
    entry = await _install(hass)
    await _add_zone(hass, entry)
    assert _numbers(hass) == ["soggiorno_temperatura_comfort", "soggiorno_temperatura_eco"]
    await _remove_zone(hass, entry, "Soggiorno")
    assert _numbers(hass) == ["soggiorno_temperatura_comfort"]


async def test_user_deletion_respected_then_recreate(hass: HomeAssistant) -> None:
    entry = await _install(hass)
    await _add_zone(hass, entry)
    await get_storage_collection(hass, "input_number").async_delete_item(
        "soggiorno_temperatura_eco"
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _numbers(hass) == ["soggiorno_temperatura_comfort"]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"dashboard": True, "recreate_missing": True}
    )
    await hass.async_block_till_done()
    assert _numbers(hass) == ["soggiorno_temperatura_comfort", "soggiorno_temperatura_eco"]
    assert "recreate_missing" not in entry.options


async def test_user_dashboard_edits_respected(hass: HomeAssistant) -> None:
    entry = await _install(hass)
    await _add_zone(hass, entry)
    await _dashboard(hass).async_save({"views": [{"title": "Mia", "cards": []}]})
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert await _config(hass) == {"views": [{"title": "Mia", "cards": []}]}


async def test_dashboard_disabled(hass: HomeAssistant) -> None:
    await _base(hass)
    entry = MockConfigEntry(domain=DOMAIN, version=2, title="Temperature Helper", options={"dashboard": False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert _dashboard(hass) is None


# ---------------------------------------------------------------- average ---


async def test_average_helper_follows_zones(hass: HomeAssistant) -> None:
    entry = await _install(hass)
    await _add_zone(hass, entry, temperature_sensor="sensor.t_soggiorno")
    await _add_zone(hass, entry, zone="Camera", temperature_sensor="sensor.t_camera")

    avg = hass.config_entries.async_entries("min_max")
    assert len(avg) == 1
    assert avg[0].options["entity_ids"] == ["sensor.t_soggiorno", "sensor.t_camera"]
    assert hass.states.get(AVG_ENTITY).state == "19.5"
    graphs = _graphs(await _config(hass))
    assert len(graphs) == 1 and set(graphs[0]["entities"]) == {TPL_ENTITY, AVG_ENTITY}

    await _remove_zone(hass, entry, "Camera")
    assert hass.config_entries.async_entries("min_max")[0].options["entity_ids"] == [
        "sensor.t_soggiorno"
    ]
    await _remove_zone(hass, entry, "Soggiorno")
    assert hass.config_entries.async_entries("min_max") == []
    assert _graphs(await _config(hass))[0]["entities"] == [TPL_ENTITY]


async def test_sensor_changed_in_reconfigure(hass: HomeAssistant) -> None:
    entry = await _install(hass)
    await _add_zone(hass, entry, temperature_sensor="sensor.t_soggiorno")
    data = {k: v for k, v in ZONE.items() if k != "zone"}
    await _reconfigure(hass, entry, "Soggiorno", {**data, "temperature_sensor": "sensor.t_camera"})
    avg = hass.config_entries.async_entries("min_max")
    assert len(avg) == 1
    assert avg[0].options["entity_ids"] == ["sensor.t_camera"]


# --------------------------------------------------------------- removal ----


async def test_remove_integration_deletes_everything(hass: HomeAssistant, hass_storage) -> None:
    entry = await _install(hass)
    await _add_zone(hass, entry, temperature_sensor="sensor.t_soggiorno")
    await _add_zone(hass, entry, zone="Camera", temperature_sensor="sensor.t_camera")
    assert _dashboard(hass) is not None

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert _numbers(hass) == []
    assert _booleans(hass) == []
    assert hass.config_entries.async_entries("min_max") == []
    assert hass.config_entries.async_entries("template") == []
    assert _dashboard(hass) is None
    assert STORE_KEY not in hass_storage
    assert not [
        e for e in er.async_get(hass).entities.values() if e.platform in ("min_max", "template")
    ]

    # reinstall starts clean
    entry = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.async_block_till_done()
    assert len(hass.config_entries.async_entries("template")) == 1
    assert _dashboard(hass) is not None


async def test_remove_keeps_preexisting_dashboard(hass: HomeAssistant) -> None:
    """A dashboard we did not create is never deleted."""
    await _base(hass)
    from custom_components.temperature_helper.helper_manager import find_storage_collection

    coll = find_storage_collection(hass, "lovelace/dashboards", "lovelace_dashboards")
    await coll.async_create_item(
        {"url_path": "temperature-helper", "title": "Mia", "show_in_sidebar": True, "require_admin": False}
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.async_block_till_done()
    assert await hass.config_entries.async_remove(result["result"].entry_id)
    await hass.async_block_till_done()
    assert _dashboard(hass) is not None


# ------------------------------------------------------------- migration ----


async def test_migrate_v1_entries(hass: HomeAssistant) -> None:
    await _base(hass)
    numbers = get_storage_collection(hass, "input_number")
    for zone in ("Soggiorno", "Camera"):
        await numbers.async_create_item({"name": f"{zone} Temperatura Comfort", "min": 5, "max": 30})
    v1 = []
    for zone, sensor in (("Soggiorno", "sensor.t_soggiorno"), ("Camera", "")):
        slug = slugify(zone)
        e = MockConfigEntry(
            domain=DOMAIN,
            version=1,
            title=zone,
            unique_id=slug,
            data={
                **ZONE,
                "zone": zone,
                "setpoints": ["comfort"],
                "manual_switch": False,
                "helpers": {"comfort": {"domain": "input_number", "id": f"{slug}_temperatura_comfort"}},
                "dashboard_placed": [],
            },
            options={"temperature_sensor": sensor},
        )
        e.add_to_hass(hass)
        v1.append(e)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    main = entries[0]
    assert main.version == 2
    assert sorted(s.title for s in main.subentries.values()) == ["Camera", "Soggiorno"]
    cam = _subentry(main, "Camera")
    assert "temperature_sensor" not in cam.data
    # helpers kept, no duplicates
    assert _numbers(hass) == ["camera_temperatura_comfort", "soggiorno_temperatura_comfort"]
    # average helper built from the migrated sensor
    assert hass.config_entries.async_entries("min_max")[0].options["entity_ids"] == [
        "sensor.t_soggiorno"
    ]
    # migrated helpers are owned: removing the zone deletes them
    await _remove_zone(hass, main, "Camera")
    assert _numbers(hass) == ["soggiorno_temperatura_comfort"]
