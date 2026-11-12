"""End-to-end tests: config flow -> native helpers."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component

from custom_components.temperature_helper.const import DATA_HELPERS, DOMAIN
from custom_components.temperature_helper.helper_manager import get_storage_collection

USER_INPUT = {
    "zone": "Soggiorno",
    "setpoints": ["comfort", "eco"],
    "min_temp": 5,
    "max_temp": 30,
    "step": 0.5,
    "manual_switch": True,
}


async def _setup(hass: HomeAssistant):
    assert await async_setup_component(hass, "input_number", {})
    assert await async_setup_component(hass, "input_boolean", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return result["result"]


def _numbers(hass):
    return sorted(get_storage_collection(hass, "input_number").data)


async def test_creates_native_helpers(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    assert _numbers(hass) == ["soggiorno_temperatura_comfort", "soggiorno_temperatura_eco"]
    assert list(get_storage_collection(hass, "input_boolean").data) == [
        "soggiorno_modalita_manuale"
    ]
    state = hass.states.get("input_number.soggiorno_temperatura_comfort")
    assert float(state.state) == 21.0
    assert state.attributes["unit_of_measurement"] == "°C"
    assert hass.states.get("input_boolean.soggiorno_modalita_manuale") is not None
    assert len(entry.data[DATA_HELPERS]) == 3


async def test_duplicate_zone_aborts(hass: HomeAssistant) -> None:
    await _setup(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reload_no_duplicates(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    for _ in range(3):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert _numbers(hass) == ["soggiorno_temperatura_comfort", "soggiorno_temperatura_eco"]


async def test_adopts_existing_helper(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "input_number", {})
    await get_storage_collection(hass, "input_number").async_create_item(
        {"name": "Soggiorno Temperatura Comfort", "min": 0, "max": 40}
    )
    await _setup(hass)
    assert _numbers(hass) == ["soggiorno_temperatura_comfort", "soggiorno_temperatura_eco"]


async def test_remove_entry_keeps_helpers(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _numbers(hass) == ["soggiorno_temperatura_comfort", "soggiorno_temperatura_eco"]
    assert hass.states.get("input_number.soggiorno_temperatura_eco") is not None


async def test_user_deletion_respected_then_recreate(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    coll = get_storage_collection(hass, "input_number")
    await coll.async_delete_item("soggiorno_temperatura_eco")
    await hass.async_block_till_done()

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _numbers(hass) == ["soggiorno_temperatura_comfort"]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    opts = {k: v for k, v in USER_INPUT.items() if k != "zone"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**opts, "setpoints": ["comfort", "eco", "night"], "recreate_missing": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert _numbers(hass) == [
        "soggiorno_temperatura_comfort",
        "soggiorno_temperatura_eco",
        "soggiorno_temperatura_notte",
    ]
    assert "recreate_missing" not in entry.options


async def _setup_with_lovelace(hass: HomeAssistant):
    assert await async_setup_component(hass, "lovelace", {})
    return await _setup(hass)


def _dashboard(hass):
    return hass.data["lovelace"].dashboards.get("temperature-helper")


def _zone_sections(config):
    return [
        s
        for s in config["views"][0]["sections"]
        if s["cards"] and s["cards"][0]["type"] == "heading"
    ]


async def test_dashboard_created(hass: HomeAssistant) -> None:
    await _setup_with_lovelace(hass)
    dash = _dashboard(hass)
    assert dash is not None and dash.mode == "storage"
    config = await dash.async_load(False)
    sections = _zone_sections(config)
    assert len(sections) == 1
    entities = [c.get("entity") for c in sections[0]["cards"]]
    assert sections[0]["cards"][0]["heading"] == "Soggiorno"
    assert set(entities[1:]) == {
        "input_number.soggiorno_temperatura_comfort",
        "input_number.soggiorno_temperatura_eco",
        "input_boolean.soggiorno_modalita_manuale",
    }


async def test_dashboard_no_duplicates_and_second_zone(hass: HomeAssistant) -> None:
    entry = await _setup_with_lovelace(hass)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, "zone": "Camera"}
    )
    await hass.async_block_till_done()

    config = await _dashboard(hass).async_load(False)
    headings = [s["cards"][0]["heading"] for s in _zone_sections(config)]
    assert headings == ["Soggiorno", "Camera"]


async def test_dashboard_new_setpoint_appended_to_zone(hass: HomeAssistant) -> None:
    entry = await _setup_with_lovelace(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    opts = {k: v for k, v in USER_INPUT.items() if k != "zone"}
    await hass.config_entries.options.async_configure(
        result["flow_id"], {**opts, "setpoints": ["comfort", "eco", "night"], "dashboard": True, "recreate_missing": False}
    )
    await hass.async_block_till_done()
    config = await _dashboard(hass).async_load(False)
    sections = _zone_sections(config)
    assert len(sections) == 1
    assert sections[0]["cards"][-1]["entity"] == "input_number.soggiorno_temperatura_notte"


async def test_dashboard_user_edits_respected(hass: HomeAssistant) -> None:
    entry = await _setup_with_lovelace(hass)
    dash = _dashboard(hass)
    await dash.async_save({"views": [{"title": "Mia", "cards": []}]})
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert await dash.async_load(False) == {"views": [{"title": "Mia", "cards": []}]}


async def test_dashboard_kept_on_remove(hass: HomeAssistant) -> None:
    entry = await _setup_with_lovelace(hass)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _dashboard(hass) is not None


async def test_dashboard_disabled(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "lovelace", {})
    assert await async_setup_component(hass, "input_number", {})
    assert await async_setup_component(hass, "input_boolean", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, "dashboard": False}
    )
    await hass.async_block_till_done()
    assert _dashboard(hass) is None


def _graphs(config):
    return [
        c
        for s in config["views"][0]["sections"]
        for c in s["cards"]
        if c["type"] == "statistics-graph"
    ]


async def test_average_helper_and_graph(hass: HomeAssistant) -> None:
    entry = await _setup_with_lovelace_sensor(hass, "Soggiorno", "sensor.t_soggiorno")
    await _add_zone(hass, "Camera", "sensor.t_camera")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    avg_entries = hass.config_entries.async_entries("min_max")
    assert len(avg_entries) == 1
    from homeassistant.util import slugify

    from custom_components.temperature_helper.const import AVERAGE_NAME

    avg_entity = f"sensor.{slugify(AVERAGE_NAME)}"
    assert avg_entries[0].title == AVERAGE_NAME
    assert avg_entries[0].options["entity_ids"] == ["sensor.t_soggiorno", "sensor.t_camera"]
    assert hass.states.get(avg_entity).state == "19.5"

    config = await _dashboard(hass).async_load(False)
    graphs = _graphs(config)
    assert len(graphs) == 1
    assert "title" not in graphs[0]
    assert avg_entity in graphs[0]["entities"]
    assert config["views"][0]["sections"][0]["cards"][0]["type"] == "statistics-graph"


async def test_average_helper_deleted_respected_for_existing_zone(hass: HomeAssistant) -> None:
    entry = await _setup_with_lovelace_sensor(hass, "Soggiorno", "sensor.t_soggiorno")
    avg = hass.config_entries.async_entries("min_max")[0]
    assert await hass.config_entries.async_remove(avg.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.config_entries.async_entries("min_max") == []


async def test_average_helper_recreated_by_new_zone(hass: HomeAssistant) -> None:
    await _setup_with_lovelace_sensor(hass, "Soggiorno", "sensor.t_soggiorno")
    avg = hass.config_entries.async_entries("min_max")[0]
    assert await hass.config_entries.async_remove(avg.entry_id)
    await hass.async_block_till_done()
    await _add_zone(hass, "Camera", "sensor.t_camera")
    entries = hass.config_entries.async_entries("min_max")
    assert len(entries) == 1
    assert entries[0].options["entity_ids"] == ["sensor.t_camera"]
    config = await _dashboard(hass).async_load(False)
    assert any(
        er_entity(hass, entries[0].entry_id) in g["entities"] for g in _graphs(config)
    )


async def test_cleanup_then_readd_zone_recreates_average(hass: HomeAssistant) -> None:
    """Remove everything (zone, helpers, dashboard) and add the zone again."""
    entry = await _setup_with_lovelace_sensor(hass, "Soggiorno", "sensor.t_soggiorno")
    assert await hass.config_entries.async_remove(entry.entry_id)
    for avg in hass.config_entries.async_entries("min_max"):
        assert await hass.config_entries.async_remove(avg.entry_id)
    await hass.async_block_till_done()

    await _add_zone(hass, "Soggiorno", "sensor.t_soggiorno")
    assert len(hass.config_entries.async_entries("min_max")) == 1


def er_entity(hass, entry_id):
    from homeassistant.helpers import entity_registry as er

    return er.async_get(hass).async_get_entity_id("sensor", "min_max", entry_id)


async def test_concurrent_setup_single_average(hass: HomeAssistant) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    assert await async_setup_component(hass, "lovelace", {})
    hass.states.async_set("sensor.t_soggiorno", "20", {"device_class": "temperature"})
    hass.states.async_set("sensor.t_camera", "19", {"device_class": "temperature"})
    entries = []
    for zone, sensor in (("Soggiorno", "sensor.t_soggiorno"), ("Camera", "sensor.t_camera")):
        e = MockConfigEntry(
            domain=DOMAIN,
            title=zone,
            unique_id=zone.lower(),
            data={**USER_INPUT, "zone": zone, "temperature_sensor": sensor, "dashboard": True, "helpers": {}},
        )
        e.add_to_hass(hass)
        entries.append(e)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert len(hass.config_entries.async_entries("min_max")) == 1
    config = await _dashboard(hass).async_load(False)
    assert len(_graphs(config)) == 1
    headings = sorted(s["cards"][0]["heading"] for s in _zone_sections(config))
    assert headings == ["Camera", "Soggiorno"]


async def test_no_sensor_graph_has_only_template(hass: HomeAssistant) -> None:
    await _setup_with_lovelace(hass)
    config = await _dashboard(hass).async_load(False)
    graphs = _graphs(config)
    assert len(graphs) == 1
    assert graphs[0]["entities"] == ["sensor.test"]


async def _add_zone(hass, zone, sensor):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**USER_INPUT, "zone": zone, **({"temperature_sensor": sensor} if sensor else {})},
    )
    await hass.async_block_till_done()
    return result["result"]


async def _setup_with_lovelace_sensor(hass, zone, sensor):
    assert await async_setup_component(hass, "lovelace", {})
    assert await async_setup_component(hass, "input_number", {})
    assert await async_setup_component(hass, "input_boolean", {})
    hass.states.async_set("sensor.t_soggiorno", "20", {"device_class": "temperature"})
    hass.states.async_set("sensor.t_camera", "19", {"device_class": "temperature"})
    return await _add_zone(hass, zone, sensor)


async def test_template_helper_created_and_in_graph(hass: HomeAssistant) -> None:
    from homeassistant.util import slugify

    from custom_components.temperature_helper.const import TEMPLATE_NAME

    # no temperature sensor: template helper must be created anyway
    entry = await _setup_with_lovelace(hass)
    tpl = hass.config_entries.async_entries("template")
    assert len(tpl) == 1
    assert tpl[0].title == TEMPLATE_NAME
    assert tpl[0].options["state"].startswith("{{0.00000001*as_timestamp(")
    assert tpl[0].options["unit_of_measurement"] == "kWh"
    assert tpl[0].options["state_class"] == "measurement"
    tpl_entity = f"sensor.{slugify(TEMPLATE_NAME)}"
    assert hass.states.get(tpl_entity) is not None

    # no duplicates on reload / second zone
    assert await hass.config_entries.async_reload(entry.entry_id)
    await _add_zone(hass, "Camera", None)
    assert len(hass.config_entries.async_entries("template")) == 1

    config = await _dashboard(hass).async_load(False)
    graphs = _graphs(config)
    assert len(graphs) == 1
    assert graphs[0]["entities"] == [tpl_entity]


async def test_graph_has_average_and_template(hass: HomeAssistant) -> None:
    await _setup_with_lovelace_sensor(hass, "Soggiorno", "sensor.t_soggiorno")
    config = await _dashboard(hass).async_load(False)
    graphs = _graphs(config)
    assert len(graphs) == 1
    assert len(graphs[0]["entities"]) == 2
