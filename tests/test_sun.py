"""Sun assist (#118): a sunny morning makes rooms that get sun wait for the sun."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cloudless_multiroom_thermostat.const import DOMAIN

from .test_integration import HALLWAY, LIVING, OFFICE, SYSTEM, _states
from .test_scheduler import _at, _every_day, _pt, _room, _schedule

pytestmark = pytest.mark.v2_schedules

# Monday 23 November 2026, 05:00 local (04:00 UTC)
EARLY = datetime(2026, 11, 23, 4, 0, tzinfo=UTC)
SEVEN = datetime(2026, 11, 23, 6, 0, tzinfo=UTC)  # 07:00 local


def _forecast(hass: HomeAssistant, condition: str, high: float = 14.0) -> list[ServiceCall]:
    calls: list[ServiceCall] = []

    async def _get(call: ServiceCall):
        calls.append(call)
        entity = call.data["entity_id"][0] if isinstance(call.data["entity_id"], list) else call.data["entity_id"]
        if call.data["type"] == "daily":
            return {entity: {"forecast": [{"datetime": SEVEN.isoformat(), "condition": condition, "temperature": high}]}}
        start = SEVEN - timedelta(hours=1)
        return {
            entity: {
                "forecast": [
                    {"datetime": (start + timedelta(hours=h)).isoformat(), "condition": condition, "temperature": 8}
                    for h in range(8)
                ]
            }
        }

    hass.services.async_register("weather", "get_forecasts", _get, supports_response=SupportsResponse.ONLY)
    return calls


@pytest.fixture
async def sunny_house(hass: HomeAssistant, hass_storage, freezer):
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to(EARLY)
    _states(hass)
    hass.states.async_set("weather.home", "sunny")
    hass.states.async_set("sensor.lux", "5000", {"device_class": "illuminance"})
    entry = MockConfigEntry(
        domain=DOMAIN, title="Heating", data=SYSTEM,
        subentries_data=[
            ConfigSubentryData(data=data, subentry_type="room", title=data["name"], unique_id=None)
            for data in (LIVING, OFFICE, HALLWAY)
        ],
    )
    entry.add_to_hass(hass)
    living = next(s.subentry_id for s in entry.subentries.values() if s.title == "Living")
    hass.config_entries.async_update_entry(entry, options={
        "feature_sun_assist": True, "sun_forecast": "weather.home", "sun_rooms": [living],
        "sun_hold_temperature": 15.0, "sun_lux_sensor": "sensor.lux", "sun_dark_below": 1000,
        "sun_check_delay": 180,
    })

    async def _fake_call(self, domain, service, data, key=None):
        return None

    with patch("custom_components.cloudless_multiroom_thermostat.controller.HeatingController._call", _fake_call):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry


WEEK = _every_day(_pt("00:00", "eco"), _pt("07:00", "warm"), _pt("22:00", "eco"))


async def test_sunny_morning_holds_until_the_check(hass: HomeAssistant, sunny_house, freezer) -> None:
    calls = _forecast(hass, "sunny")
    await _schedule(hass, "climate.living", WEEK)
    await _schedule(hass, "climate.office", WEEK)
    await _at(hass, freezer, SEVEN)
    await hass.async_block_till_done()
    living = _room(hass, "living")
    assert living["preset_mode"] == "warm" and living["temperature"] == 15.0
    assert living["sun_assist"] == {"status": "holding", "hold": 15.0, "check_at": "2026-11-23T10:00:00+01:00"}
    assert _room(hass, "office")["temperature"] == 18.0  # doesn't get sun
    assert calls and calls[0].data["type"] == "hourly"
    # Bright and the room warm enough at the check: keeps waiting for the sun (one check)
    hass.states.async_set("sensor.living_temp", "17.0", {"device_class": "temperature"})
    await _at(hass, freezer, SEVEN + timedelta(hours=3))
    assert _room(hass, "living")["sun_assist"]["check_at"] is None
    assert _room(hass, "living")["temperature"] == 15.0
    # The next switch point ends it
    await _at(hass, freezer, datetime(2026, 11, 23, 21, 0, tzinfo=UTC))
    assert _room(hass, "living")["sun_assist"] is None


async def test_still_dark_at_the_check_starts_the_preset(hass: HomeAssistant, sunny_house, freezer) -> None:
    _forecast(hass, "sunny")
    await _schedule(hass, "climate.living", WEEK)
    await _at(hass, freezer, SEVEN)
    hass.states.async_set("sensor.lux", "200")
    await _at(hass, freezer, SEVEN + timedelta(hours=3))
    living = _room(hass, "living")
    assert living["temperature"] == 19.0 and living["sun_assist"] is None


async def test_still_cold_at_the_check_starts_the_preset(hass: HomeAssistant, sunny_house, freezer) -> None:
    _forecast(hass, "sunny")
    await _schedule(hass, "climate.living", WEEK)
    await _at(hass, freezer, SEVEN)
    hass.states.async_set("sensor.living_temp", "15.5", {"device_class": "temperature"})
    await _at(hass, freezer, SEVEN + timedelta(hours=3))
    assert _room(hass, "living")["temperature"] == 19.0


async def test_sunny_but_not_mild_warms_up(hass: HomeAssistant, sunny_house, freezer) -> None:
    _forecast(hass, "sunny", high=9.0)
    await _schedule(hass, "climate.living", WEEK)
    await _at(hass, freezer, SEVEN)
    await hass.async_block_till_done()
    assert _room(hass, "living")["temperature"] == 19.0


async def test_without_mild_condition_sun_alone_decides(hass: HomeAssistant, sunny_house, freezer) -> None:
    hass.config_entries.async_update_entry(sunny_house, options={**sunny_house.options, "sun_mild_above": None})
    await hass.async_block_till_done()
    _forecast(hass, "sunny", high=5.0)
    await _schedule(hass, "climate.living", WEEK)
    await _at(hass, freezer, SEVEN)
    await hass.async_block_till_done()
    assert _room(hass, "living")["temperature"] == 15.0


async def test_cloudy_morning_warms_up_as_scheduled(hass: HomeAssistant, sunny_house, freezer) -> None:
    _forecast(hass, "cloudy")
    await _schedule(hass, "climate.living", WEEK)
    await _at(hass, freezer, SEVEN)
    await hass.async_block_till_done()
    assert _room(hass, "living")["temperature"] == 19.0


async def test_outside_the_window_never_waits(hass: HomeAssistant, sunny_house, freezer) -> None:
    _forecast(hass, "sunny")
    week = _every_day(_pt("00:00", "eco"), _pt("13:00", "warm"))
    await _schedule(hass, "climate.living", week)
    await _at(hass, freezer, datetime(2026, 11, 23, 12, 0, tzinfo=UTC))
    assert _room(hass, "living")["temperature"] == 19.0


async def test_failed_forecast_warms_up_and_is_tried_again(hass: HomeAssistant, sunny_house, freezer) -> None:
    async def _broken(call: ServiceCall):
        raise RuntimeError("no forecast")

    hass.services.async_register("weather", "get_forecasts", _broken, supports_response=SupportsResponse.ONLY)
    await _schedule(hass, "climate.living", WEEK)
    await _at(hass, freezer, SEVEN)
    await hass.async_block_till_done()
    assert _room(hass, "living")["temperature"] == 19.0
    # An hour later the forecast works and says sunny: back to holding, checked after the delay
    hass.services.async_remove("weather", "get_forecasts")
    _forecast(hass, "sunny")
    await _at(hass, freezer, SEVEN + timedelta(hours=1))
    await hass.async_block_till_done()
    living = _room(hass, "living")
    assert living["temperature"] == 15.0
    assert living["sun_assist"]["check_at"] == "2026-11-23T11:00:00+01:00"


async def test_forecast_is_tried_twice_at_most(hass: HomeAssistant, sunny_house, freezer) -> None:
    calls: list[ServiceCall] = []

    async def _broken(call: ServiceCall):
        calls.append(call)
        raise RuntimeError("no forecast")

    hass.services.async_register("weather", "get_forecasts", _broken, supports_response=SupportsResponse.ONLY)
    await _schedule(hass, "climate.living", WEEK)
    for hours in (0, 1, 2, 3, 4):
        await _at(hass, freezer, SEVEN + timedelta(hours=hours, seconds=1))
        await hass.async_block_till_done()
    assert len(calls) == 3 * 2  # the first try and two retries, hourly and daily each
    assert _room(hass, "living")["temperature"] == 19.0


async def test_change_by_hand_beats_sun_assist(hass: HomeAssistant, sunny_house, freezer) -> None:
    _forecast(hass, "sunny")
    await _schedule(hass, "climate.living", WEEK)
    await _at(hass, freezer, SEVEN)
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": "climate.living", "temperature": 21}, blocking=True
    )
    await hass.async_block_till_done()
    living = _room(hass, "living")
    assert living["temperature"] == 21.0 and living["sun_assist"] is None


async def test_started_after_the_check_time_warms_up(hass: HomeAssistant, sunny_house, freezer) -> None:
    """HA (re)started in the afternoon: a morning switch point is not decided late."""
    calls = _forecast(hass, "sunny")
    await _schedule(hass, "climate.living", WEEK)
    await _at(hass, freezer, SEVEN + timedelta(hours=4))  # 11:00, past the 10:00 check
    assert not calls
    assert _room(hass, "living")["temperature"] == 19.0
