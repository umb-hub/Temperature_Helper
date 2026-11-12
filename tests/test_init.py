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


async def test_dashboard_created(hass: HomeAssistant) -> None:
    await _setup_with_lovelace(hass)
    dash = _dashboard(hass)
    assert dash is not None and dash.mode == "storage"
    config = await dash.async_load(False)
    sections = config["views"][0]["sections"]
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
    headings = [s["cards"][0]["heading"] for s in config["views"][0]["sections"]]
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
    sections = config["views"][0]["sections"]
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
