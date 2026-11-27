"""Features page (#120): a feature that is off has no page, no entities, and is ignored."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError

from custom_components.cloudless_multiroom_thermostat.const import DOMAIN

from .test_integration import SENSOR_STEP, _room_step, _tick, setup  # noqa: F401 - fixture

OFF = {"feature_presence": False, "feature_windows": False, "feature_guest_mode": False, "experimental": False}


async def _features(hass: HomeAssistant, entry, **changes):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "features"})
    current = {k: v["suggested_value"] for k, v in (
        (str(key), key.description) for key in result["data_schema"].schema
    )}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {**current, **changes})
    await hass.async_block_till_done()
    return result


async def test_upgraded_system_keeps_what_it_used(hass: HomeAssistant, setup) -> None:  # noqa: F811
    entry, _ = setup
    ctl = entry.runtime_data
    assert ctl.feature("feature_presence") is True  # a presence entity is set
    assert ctl.feature("feature_windows") is True  # Living has a garden door
    assert ctl.feature("feature_guest_mode") is False
    assert hass.states.get("binary_sensor.living_window") is not None
    assert hass.states.get("switch.heating_someone_is_home_guest_mode") is None


async def test_windows_off_hides_and_ignores_them(hass: HomeAssistant, setup) -> None:  # noqa: F811
    entry, _ = setup
    result = await _features(hass, entry, feature_windows=False)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert hass.states.get("binary_sensor.living_window") is None
    hass.states.async_set("binary_sensor.garden_door", "on")
    await _tick(hass, 200)
    assert hass.states.get("climate.living").attributes["window_open"] is False
    # Edit room shows no window fields and keeps the stored ones
    living = next(s for s in entry.subentries.values() if s.title == "Living")
    flows = hass.config_entries.subentries
    result = await entry.start_subentry_reconfigure_flow(hass, living.subentry_id)
    result = await flows.async_configure(result["flow_id"], _room_step("Living"))
    assert "window_sensors" not in {str(k) for k in result["data_schema"].schema}
    sensors = {k: v for k, v in SENSOR_STEP.items() if not k.startswith("window")}
    result = await flows.async_configure(result["flow_id"], {**sensors, "temperature_sensor": "sensor.living_temp"})
    await hass.async_block_till_done()
    assert entry.subentries[living.subentry_id].data["window_sensors"] == ["binary_sensor.garden_door"]


async def test_presence_off_ignores_away(hass: HomeAssistant, setup) -> None:  # noqa: F811
    entry, _ = setup
    await _features(hass, entry, feature_presence=False)
    hass.states.async_set("input_boolean.somebody_home", "off")
    await _tick(hass)
    assert entry.runtime_data.present is True
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "presence" not in result["menu_options"]


async def test_switching_presence_on_asks_for_the_entity(hass: HomeAssistant, setup) -> None:  # noqa: F811
    entry, _ = setup
    hass.config_entries.async_update_entry(entry, data={**entry.data, "presence_entity": None})
    await hass.async_block_till_done()
    result = await _features(hass, entry, feature_presence=True)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "presence"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"presence_entity": "input_boolean.somebody_home", "away_mode": "eco"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["presence_entity"] == "input_boolean.somebody_home"
    assert entry.options["feature_presence"] is True


async def test_guest_mode_on_adds_the_switch(hass: HomeAssistant, setup) -> None:  # noqa: F811
    entry, _ = setup
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "set_guest_mode", {}, blocking=True)
    assert err.value.translation_key == "feature_off"
    await _features(hass, entry, feature_guest_mode=True)
    assert hass.states.get("switch.heating_someone_is_home_guest_mode") is not None


async def test_settings_keep_the_feature_settings(hass: HomeAssistant, setup) -> None:  # noqa: F811
    entry, _ = setup
    await _features(hass, entry, feature_guest_mode=True)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "settings"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"heat_source_entity": "climate.boiler", "off_temperature": 9, "skip_unchanged_writes": True,
         "external_temp_heartbeat": 60},
    )
    await hass.async_block_till_done()
    assert entry.options["feature_guest_mode"] is True and entry.options["off_temperature"] == 9


async def test_sun_assist_on_opens_its_page(hass: HomeAssistant, setup) -> None:  # noqa: F811
    entry, _ = setup
    hass.states.async_set("weather.home", "sunny")
    result = await _features(hass, entry, feature_sun_assist=True)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "sun_assist"
    living = next(s.subentry_id for s in entry.subentries.values() if s.title == "Living")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"sun_forecast": "weather.home", "sun_conditions": ["sunny"], "sun_rooms": [living],
         "sun_hold_temperature": 15, "sun_window_start": "05:00:00", "sun_window_end": "12:00:00",
         "sun_dark_below": 1000, "sun_check_delay": 180},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["sun_rooms"] == [living] and entry.options["sun_lux_sensor"] is None
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "sun_assist" in result["menu_options"]
