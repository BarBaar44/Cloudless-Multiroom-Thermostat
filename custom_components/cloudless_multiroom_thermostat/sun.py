"""Sun assist (#118): rooms that get sun hold a lower temperature on a sunny morning.

A switch point inside the morning window to a preset warmer than the hold
temperature, in a room that gets sun: when the forecast is sunny (and mild,
when a forecast temperature is set), the room holds the hold temperature
instead. At the check time (the switch point plus the check delay) the preset
starts when the room is still cold, or when the optional lux sensor still
reads dark; otherwise the room keeps holding until its next switch point.
One check only. A forecast that can't be read starts the preset and is tried
again twice, an hour apart; if it then says sunny, the room goes back to
holding.

The decision belongs to one switch point (its instant): the next switch point
ends it. While the forecast is being read, the room already holds, so the
heating doesn't start for a moment and stop again. Decisions are kept in the
schedule file (`sun`), so a restart during a hold keeps it.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Final

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .features import FEATURE_SUN

if TYPE_CHECKING:
    from .controller import Room
    from .scheduler import Scheduler

_LOGGER = logging.getLogger(__name__)

CONF_SUN_FORECAST: Final = "sun_forecast"
CONF_SUN_CONDITIONS: Final = "sun_conditions"
CONF_SUN_HOLD: Final = "sun_hold_temperature"
CONF_SUN_LUX: Final = "sun_lux_sensor"
CONF_SUN_DARK_BELOW: Final = "sun_dark_below"
CONF_SUN_CHECK_DELAY: Final = "sun_check_delay"  # minutes
CONF_SUN_COLD_BELOW: Final = "sun_cold_below"
CONF_SUN_MILD_ABOVE: Final = "sun_mild_above"  # forecast temperature; empty: no condition
CONF_SUN_WINDOW_START: Final = "sun_window_start"
CONF_SUN_WINDOW_END: Final = "sun_window_end"
CONF_SUN_ROOMS: Final = "sun_rooms"

SUN_CONDITIONS: Final = ["sunny", "partlycloudy", "clear-night", "cloudy", "fog", "rainy", "snowy", "windy"]
DEFAULT_SUN_CONDITIONS: Final = ["sunny", "partlycloudy"]
DEFAULT_SUN_HOLD: Final = 15.0
DEFAULT_SUN_DARK_BELOW: Final = 1000.0  # lux
DEFAULT_SUN_CHECK_DELAY: Final = 60  # minutes
DEFAULT_SUN_COLD_BELOW: Final = 16.0
DEFAULT_SUN_MILD_ABOVE: Final = 12.0
RETRIES: Final = 2
RETRY_AFTER: Final = timedelta(hours=1)
DEFAULT_SUN_WINDOW_START: Final = "05:00:00"
DEFAULT_SUN_WINDOW_END: Final = "12:00:00"
SUNNY_SHARE: Final = 0.5  # at least half of the forecast hours up to the check

PENDING: Final = "pending"  # reading the forecast; the room holds meanwhile
HOLDING: Final = "holding"
STARTED: Final = "started"  # not sunny, or still dark at the check: the preset runs
STATUSES: Final = (PENDING, HOLDING, STARTED)


def _time(value: Any, default: str) -> time:
    try:
        return time.fromisoformat(str(value or default))
    except ValueError:
        return time.fromisoformat(default)


class SunAssist:
    """Decides, per room and switch point, whether the sun takes over the warm-up."""

    def __init__(self, hass: HomeAssistant, scheduler: Scheduler) -> None:
        self.hass = hass
        self.scheduler = scheduler
        self._tasks: set[str] = set()

    # ------------------------------------------------------------ settings
    @property
    def _settings(self) -> dict[str, Any]:
        return self.scheduler.controller.settings

    @property
    def on(self) -> bool:
        return self.scheduler.controller.feature(FEATURE_SUN) and bool(self._settings.get(CONF_SUN_FORECAST))

    @property
    def hold_temp(self) -> float:
        return float(self._settings.get(CONF_SUN_HOLD) or DEFAULT_SUN_HOLD)

    @property
    def check_delay(self) -> timedelta:
        return timedelta(minutes=int(self._settings.get(CONF_SUN_CHECK_DELAY) or DEFAULT_SUN_CHECK_DELAY))

    def _state(self) -> dict[str, Any]:
        return self.scheduler.data.setdefault("sun", {})

    def _in_window(self, instant: datetime) -> bool:
        local = dt_util.as_local(instant).time()
        start = _time(self._settings.get(CONF_SUN_WINDOW_START), DEFAULT_SUN_WINDOW_START)
        end = _time(self._settings.get(CONF_SUN_WINDOW_END), DEFAULT_SUN_WINDOW_END)
        return start <= local < end

    def applies(self, room: Room, instant: datetime, target: float) -> bool:
        return (
            self.on
            and room.room_id in (self._settings.get(CONF_SUN_ROOMS) or [])
            and target > self.hold_temp
            and self._in_window(instant)
        )

    # ------------------------------------------------------------ decision
    @callback
    def hold_for(self, room: Room, instant: datetime, target: float, now: datetime) -> float | None:
        """The temperature the room holds instead of `target`, or None to run the preset."""
        state = self._state()
        if not self.applies(room, instant, target):
            state.pop(room.room_id, None)
            return None
        key = instant.isoformat()
        rec = state.get(room.room_id)
        if rec is None or rec.get("point") != key:
            rec = {"point": key, "status": PENDING, "check_at": None}
            state[room.room_id] = rec
            self.scheduler.store.async_delay_save()
        retry_due = (
            rec["status"] == STARTED and rec.get("retry_at") and dt_util.parse_datetime(rec["retry_at"]) <= now
        )
        if (rec["status"] == PENDING or retry_due) and room.room_id not in self._tasks:
            self._tasks.add(room.room_id)
            self.hass.async_create_task(self._async_decide(room, instant), eager_start=False)
        if rec["status"] == HOLDING and rec.get("check_at") and dt_util.parse_datetime(rec["check_at"]) <= now:
            rec["check_at"] = None  # one check only
            rec["status"] = STARTED if self._still_cold(room) or self._dark() else HOLDING
            self.scheduler.store.async_delay_save()
        return None if rec["status"] == STARTED else self.hold_temp

    async def _async_decide(self, room: Room, instant: datetime) -> None:
        try:
            sunny = await self._async_sunny(instant)
        except Exception:  # noqa: BLE001 - a forecast problem must never stop the heating
            _LOGGER.debug("Sun assist: forecast failed", exc_info=True)
            sunny = None
        finally:
            self._tasks.discard(room.room_id)
        rec = self._state().get(room.room_id)
        if rec is None or rec.get("point") != instant.isoformat():
            return  # the schedule moved on meanwhile
        now = dt_util.utcnow()
        retrying = rec["status"] == STARTED
        if sunny:
            rec.update(status=HOLDING, check_at=((now if retrying else instant) + self.check_delay).isoformat())
            rec.pop("retry_at", None)
        elif sunny is None:
            # Can't read the forecast: warm up as scheduled, try again in an hour (twice)
            left = (rec.get("retries", RETRIES + 1) if retrying else RETRIES + 1) - 1
            rec.update(status=STARTED, retries=left, retry_at=(now + RETRY_AFTER).isoformat() if left > 0 else None)
            _LOGGER.warning(
                "Sun assist: forecast of %s couldn't be read; %s warms up as scheduled%s",
                self._settings.get(CONF_SUN_FORECAST), room.name, ", trying again in an hour" if left > 0 else "",
            )
        else:
            rec.update(status=STARTED, retry_at=None)
        _LOGGER.debug("Sun assist %s: %s", room.name, rec)
        self.scheduler.store.async_delay_save()
        self.scheduler.apply()

    async def _async_forecast(self, entity_id: str, kind: str) -> list[dict[str, Any]]:
        try:
            response = await self.hass.services.async_call(
                "weather", "get_forecasts", {"entity_id": entity_id, "type": kind},
                blocking=True, return_response=True,
            )
        except Exception:  # noqa: BLE001 - not every weather entity offers every type
            return []
        return list((response or {}).get(entity_id, {}).get("forecast") or [])

    async def _async_sunny(self, instant: datetime) -> bool | None:
        """Sunny (and mild, when set) for this switch point; None when the forecast can't be read."""
        entity_id = self._settings[CONF_SUN_FORECAST]
        conditions = set(self._settings.get(CONF_SUN_CONDITIONS) or DEFAULT_SUN_CONDITIONS)
        mild = self._settings.get(CONF_SUN_MILD_ABOVE, DEFAULT_SUN_MILD_ABOVE)
        until = instant + self.check_delay
        hourly = await self._async_forecast(entity_id, "hourly")
        daily = await self._async_forecast(entity_id, "daily")
        hours = [
            f for f in hourly
            if (at := dt_util.parse_datetime(str(f.get("datetime"))))
            and instant - timedelta(hours=1) < at <= until
        ]
        if hours:
            sunny = sum(f.get("condition") in conditions for f in hours) >= SUNNY_SHARE * len(hours)
        elif daily:
            sunny = daily[0].get("condition") in conditions
        else:
            return None
        if not sunny or mild in (None, ""):
            return sunny
        # Mild: today's forecast high, as the daily forecast gives it; else the hourly maximum today
        if daily and daily[0].get("temperature") is not None:
            high = float(daily[0]["temperature"])
        else:
            today = dt_util.as_local(instant).date()
            temps = [
                float(f["temperature"]) for f in hourly
                if f.get("temperature") is not None
                and (at := dt_util.parse_datetime(str(f.get("datetime"))))
                and dt_util.as_local(at).date() == today
            ]
            if not temps:
                return None
            high = max(temps)
        return high > float(mild)

    def _still_cold(self, room: Room) -> bool:
        """At the check: the room is below Still cold below (or its temperature is unknown)."""
        cold = float(self._settings.get(CONF_SUN_COLD_BELOW) or DEFAULT_SUN_COLD_BELOW)
        return room.current is None or room.current < cold

    def _dark(self) -> bool:
        """Still dark at the check: the preset starts. An unreadable sensor counts as dark."""
        if not self._settings.get(CONF_SUN_LUX):
            return False
        state = self.hass.states.get(self._settings[CONF_SUN_LUX])
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return True
        try:
            return float(state.state) < float(self._settings.get(CONF_SUN_DARK_BELOW) or DEFAULT_SUN_DARK_BELOW)
        except ValueError:
            return True

    # ---------------------------------------------------------------- card
    def attributes(self, room: Room) -> dict[str, Any] | None:
        rec = (self.scheduler.data or {}).get("sun", {}).get(room.room_id)
        if not self.on or rec is None or rec["status"] == STARTED:
            return None
        check = rec.get("check_at")
        return {
            "status": rec["status"],
            "hold": self.hold_temp,
            "check_at": None if check is None else dt_util.as_local(dt_util.parse_datetime(check)).isoformat(),
        }

    def moments(self) -> list[datetime]:
        """Check times the scheduler's timer must wake up for."""
        out = []
        for rec in ((self.scheduler.data or {}).get("sun") or {}).values():
            if rec.get("status") == HOLDING and rec.get("check_at"):
                out.append(dt_util.parse_datetime(rec["check_at"]))
            if rec.get("status") == STARTED and rec.get("retry_at"):
                out.append(dt_util.parse_datetime(rec["retry_at"]))
        return out
