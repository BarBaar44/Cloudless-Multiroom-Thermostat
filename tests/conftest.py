"""Test fixtures."""

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ from the repo."""
    yield


@pytest.fixture(autouse=True)
def v1_rooms_have_scheduling_off(request, monkeypatch):
    """Tests written before v2 expect v1 behaviour: rooms without a schedule get scheduling off.

    Tests of the scheduler itself are marked `v2_schedules` and see the real
    behaviour (a room without a schedule holds 15 °C).
    """
    if request.node.get_closest_marker("v2_schedules"):
        yield
        return
    from custom_components.cloudless_multiroom_thermostat.schedule_store import (  # noqa: PLC0415
        ScheduleStore,
    )

    original = ScheduleStore.async_load

    async def _load(self, rooms, defaults):
        await original(self, rooms, defaults)
        if self.data is not None:
            for room_id in rooms:
                self.data["rooms"].setdefault(room_id, {"scheduling": "off", "week": None})

    monkeypatch.setattr(ScheduleStore, "async_load", _load)
    yield
