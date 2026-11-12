"""Template helper gets past hourly statistics at creation."""

from datetime import timedelta

import pytest
from homeassistant import config_entries
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.temperature_helper.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Recorder must be set up before hass (overrides the conftest fixture)."""
    yield


async def test_template_statistics_backfilled(hass: HomeAssistant) -> None:
    for comp in ("lovelace", "input_number", "input_boolean"):
        assert await async_setup_component(hass, comp, {})
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    now = dt_util.utcnow()
    stats = await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        now - timedelta(days=8),
        None,
        {"sensor.test"},
        "hour",
        None,
        {"mean", "min", "max"},
    )
    rows = stats["sensor.test"]
    assert len(rows) == 7 * 24
    first = rows[0]
    assert first["min"] < first["mean"] < first["max"]
    assert abs(first["mean"] - 1e-8 * (first["start"] + 1800)) < 1e-6


async def test_existing_template_backfilled_once(hass: HomeAssistant) -> None:
    """Upgrade case: helper exists, never backfilled -> backfilled at next load."""
    from custom_components.temperature_helper.average_manager import SharedState

    for comp in ("lovelace", "input_number", "input_boolean"):
        assert await async_setup_component(hass, comp, {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.async_block_till_done()
    entry = result["result"]
    shared = await SharedState(hass).async_load()
    assert shared.data["template_backfilled"] is True
    await shared.async_set(template_backfilled=False)  # simulate v2.0.0 state

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    shared = await SharedState(hass).async_load()
    assert shared.data["template_backfilled"] is True
